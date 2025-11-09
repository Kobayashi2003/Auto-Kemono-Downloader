import time
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from queue import Queue
from typing import Dict, List, Optional

from .models import DownloadTask, QueueStatus, TaskStatus, TaskType
from .storage import Storage
from .downloader import Downloader


class Scheduler:
    def __init__(
        self,
        storage: Storage,
        downloader: Downloader,
        global_timer: Optional[Dict],
        max_workers: int = 3,
    ):
        self.storage = storage
        self.downloader = downloader
        self.global_timer = global_timer
        self.max_workers = max_workers
        self.running = False
        self.scheduler_thread = None
        self.next_runs = {}

        self.task_queue: Queue[DownloadTask] = Queue()
        self.queued_tasks: set = set()
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.completed_tasks: List[DownloadTask] = []
        self.max_history = 100

        self.executor: Optional[ThreadPoolExecutor] = None
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return
        self.running = True
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def stop(self):
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        if self.executor:
            # self.executor.shutdown(wait=True)
            self.executor.shutdown(wait=False, cancel_futures=True)

    def cancel_all_tasks(self):
        """Cancel all queued and running tasks"""
        import time

        # Step 1: Clear queued tasks
        with self.lock:
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except:
                    break
            self.queued_tasks.clear()
            active_count = len(self.active_tasks)

        # Step 2: Stop downloader (sets stop flag)
        self.downloader.stop()

        # Step 3: Wait for active tasks to finish (if any)
        if active_count > 0:
            max_wait = 10
            wait_interval = 0.1
            elapsed = 0

            while elapsed < max_wait:
                with self.lock:
                    if len(self.active_tasks) == 0:
                        break
                time.sleep(wait_interval)
                elapsed += wait_interval

            # Check if any tasks are still running
            with self.lock:
                remaining = len(self.active_tasks)
                if remaining > 0:
                    print(f"Warning: {remaining} tasks still running after {max_wait}s timeout")

        # Step 4: Resume downloader for future tasks
        self.downloader.resume()

        return active_count

    def queue_manual(
        self, artist_id: str, from_date: Optional[str] = None, until_date: Optional[str] = None
    ) -> bool:
        task = DownloadTask(artist_id, from_date, until_date, TaskType.MANUAL)
        return self._add_task(task)

    def queue_batch(self, artist_ids: List[str]) -> int:
        added = 0
        for artist_id in artist_ids:
            task = DownloadTask(artist_id, None, None, TaskType.MANUAL)
            if self._add_task(task):
                added += 1
        return added

    def _add_task(self, task: DownloadTask) -> bool:
        with self.lock:
            if task in self.queued_tasks:
                return False
            self.queued_tasks.add(task)
            self.task_queue.put(task)
            return True

    def get_queue_status(self) -> QueueStatus:
        with self.lock:
            return QueueStatus(
                queued=self.task_queue.qsize(),
                running=len(self.active_tasks),
                completed=len(self.completed_tasks),
            )

    def list_active_tasks(self) -> List[DownloadTask]:
        with self.lock:
            return list(self.active_tasks.values())

    def list_queued_tasks(self) -> List[DownloadTask]:
        with self.lock:
            return list(self.task_queue.queue)

    def _scheduler_loop(self):
        while self.running:
            try:
                self._check_scheduled_tasks()
                self._process_queue()
                time.sleep(1)
            except Exception as e:
                print(f"Scheduler error: {e}")
                time.sleep(5)

    def _process_queue(self):
        with self.lock:
            active_count = len(self.active_tasks)
            if active_count >= self.max_workers:
                return

            if self.task_queue.empty():
                return

            task = self.task_queue.get_nowait()
            self.queued_tasks.discard(task)
            self.active_tasks[task.artist_id] = task

        future = self.executor.submit(self._execute_task, task)
        future.add_done_callback(lambda f: self._task_completed(task, f))

    def _execute_task(self, task: DownloadTask):
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        try:
            artist = self.storage.get_artist(task.artist_id)
            if not artist:
                raise Exception(f"Artist {task.artist_id} not found")

            manual = task.task_type == TaskType.MANUAL
            result = self.downloader.download_artist(artist, task.from_date, task.until_date, manual)

            task.status = TaskStatus.COMPLETED
            task.result = result
            return result

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            raise

        finally:
            task.finished_at = datetime.now()

    def _task_completed(self, task: DownloadTask, future: Future):
        with self.lock:
            self.active_tasks.pop(task.artist_id, None)
            self.completed_tasks.append(task)
            if len(self.completed_tasks) > self.max_history:
                self.completed_tasks.pop(0)

    def _check_scheduled_tasks(self):
        artists = self.storage.get_artists()
        for artist in artists:
            if artist.ignore or artist.completed:
                continue

            timer = artist.timer or self.global_timer
            if not timer:
                continue

            if self._should_run(artist.id, timer):
                task = DownloadTask(artist.id, None, None, TaskType.SCHEDULED)
                self._add_task(task)

    def _should_run(self, artist_id: str, timer: Dict) -> bool:
        now = datetime.now()

        if artist_id not in self.next_runs:
            self.next_runs[artist_id] = self._calc_next(timer, now)

        if now >= self.next_runs[artist_id]:
            self.next_runs[artist_id] = self._calc_next(timer, now)
            return True

        return False

    def _calc_next(self, timer: Dict, from_time: datetime) -> datetime:
        timer_type = timer.get("type", "daily")
        timer_time = timer.get("time", "00:00")
        hour, minute = map(int, timer_time.split(":"))

        next_run = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if timer_type == "daily":
            if next_run <= from_time:
                next_run += timedelta(days=1)
        elif timer_type == "weekly":
            day = timer.get("day", 0)
            days_ahead = day - from_time.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_run += timedelta(days=days_ahead)
        elif timer_type == "monthly":
            day = timer.get("day", 1)
            next_run = next_run.replace(day=day)
            if next_run <= from_time:
                if from_time.month == 12:
                    next_run = next_run.replace(year=from_time.year + 1, month=1)
                else:
                    next_run = next_run.replace(month=from_time.month + 1)

        return next_run
