from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


# ==================== Constants ====================

# Content marker for posts without content
NO_CONTENT_MARKER = "<NO_CONTENT>"


# ==================== History ====================

@dataclass
class HistoryRecord:
    """Command history record"""
    command: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    success: bool = True
    artist_id: Optional[str] = None
    params: Dict = field(default_factory=dict)
    note: str = ""


# ==================== Core Data Models ====================

@dataclass
class Artist:
    """Artist/Creator information"""
    id: str
    service: str
    user_id: str
    name: str
    url: str
    alias: str = ""
    last_date: Optional[str] = None
    timer: Optional[Dict] = None
    ignore: bool = False
    completed: bool = False
    config: Dict = field(default_factory=dict)
    filter: Dict = field(default_factory=dict)

    def display_name(self) -> str:
        return self.alias or self.name


@dataclass
class Post:
    """Post/Content information"""
    id: str
    user: str
    service: str
    title: str
    content: str
    embed: Dict
    shared_file: bool
    added: str
    published: str
    edited: Optional[str]
    file: Optional[Dict]
    attachments: List[Dict]
    done: bool = False
    failed_files: List[str] = field(default_factory=list)


@dataclass
class Profile:
    """Artist profile from API"""
    id: str
    name: str
    service: str
    indexed: str
    updated: str
    public_id: str
    relation_id: Optional[str]
    post_count: int
    dm_count: int
    share_count: int
    chat_count: int
    cached_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ==================== Configuration ====================

@dataclass
class Config:
    """Application configuration"""
    # Directories
    cache_dir: str = "cache"
    logs_dir: str = "logs"
    temp_dir: str = "temp"
    download_dir: str = "downloads"

    # Scheduling & Filtering
    global_timer: Optional[Dict] = None
    global_filter: Dict = field(default_factory=dict)

    # Network
    max_retries: int = 3
    retry_delay: int = 5
    request_timeout: int = 30

    # Concurrency (max total concurrent downloads = max_concurrent_artists × max_concurrent_posts × max_concurrent_files)
    max_concurrent_artists: int = 3
    max_concurrent_posts: int = 5
    max_concurrent_files: int = 10

    # Templates
    date_format: str = "%Y.%m.%d"
    artist_folder_template: str = "{service}/{name}"
    post_folder_template: str = "[{published}] {title}"
    file_template: str = "{idx}"
    path_template: Optional[str] = None  # Deprecated

    # Download Behavior
    save_content: bool = True
    save_empty_posts: bool = False
    rename_images_only: bool = True
    image_extensions: set = field(default_factory=lambda: {'.jpe', '.jpg', '.jpeg', '.png', '.gif', '.webp'})

    # Proxy
    use_proxy: bool = False
    proxy_base_port: int = 7890
    proxy_num_instances: int = 10
    clash_exe_path: str = ""
    clash_config_path: str = ""
    proxy_skip_keywords: List[str] = field(default_factory=lambda: ['DIRECT', 'REJECT'])


# ==================== Template Parameters ====================

@dataclass
class ArtistFolderParams:
    """Parameters for artist folder template formatting"""
    service: str
    name: str
    alias: str = ""
    user_id: str = ""
    last_date: str = ""


@dataclass
class PostFolderParams:
    """Parameters for post folder template formatting"""
    id: str
    user: str
    service: str
    title: str
    published: str


@dataclass
class FileParams:
    """Parameters for file template formatting"""
    name: str
    idx: int


# ==================== Download Results ====================

@dataclass
class DownloadPostResult:
    """Result of downloading a single post"""
    service: str
    post_id: str
    success: bool
    files_downloaded: int = 0
    files_failed: int = 0
    failed_files: List[str] = field(default_factory=list)

    @staticmethod
    def empty(service: str, post_id: str) -> 'DownloadPostResult':
        """Create empty successful result (no files to download)"""
        return DownloadPostResult(
            service=service,
            post_id=post_id,
            success=True,
            files_downloaded=0,
            files_failed=0,
            failed_files=[]
        )

    @staticmethod
    def failed(service: str, post_id: str) -> 'DownloadPostResult':
        """Create failed post result"""
        return DownloadPostResult(
            service=service,
            post_id=post_id,
            success=False,
            files_downloaded=0,
            files_failed=0,
            failed_files=[]
        )


@dataclass
class DownloadPostsResult:
    """Result of downloading multiple posts"""
    success: bool
    posts_downloaded: int = 0
    posts_failed: int = 0
    failed_posts: List[DownloadPostResult] = field(default_factory=list)

    @staticmethod
    def empty() -> 'DownloadPostsResult':
        """Create empty successful result (no posts to process)"""
        return DownloadPostsResult(
            success=True,
            posts_downloaded=0,
            posts_failed=0,
            failed_posts=[]
        )

    @staticmethod
    def failed() -> 'DownloadPostsResult':
        """Create failed result (all posts failed)"""
        return DownloadPostsResult(
            success=False,
            posts_downloaded=0,
            posts_failed=0,
            failed_posts=[]
        )


@dataclass
class DownloadArtistResult(DownloadPostsResult):
    """Result of downloading an artist's posts"""
    artist_id: str = ""

    @staticmethod
    def empty(artist_id: str) -> 'DownloadArtistResult':
        """Create empty successful result (no posts to process)"""
        return DownloadArtistResult(
            artist_id=artist_id,
            success=True,
            posts_downloaded=0,
            posts_failed=0,
            failed_posts=[]
        )

    @staticmethod
    def failed(artist_id: str) -> 'DownloadArtistResult':
        """Create failed artist result"""
        return DownloadArtistResult(
            artist_id=artist_id,
            success=False,
            posts_downloaded=0,
            posts_failed=0,
            failed_posts=[]
        )

    @staticmethod
    def skipped(artist_id: str) -> 'DownloadArtistResult':
        """Create skipped artist result (marked as completed)"""
        return DownloadArtistResult(
            artist_id=artist_id,
            success=True,
            posts_downloaded=0,
            posts_failed=0,
            failed_posts=[]
        )


# ==================== Validation Models ====================

@dataclass
class ValidationLevel:
    """Validation level configuration"""
    artist_unique: bool = True  # artist_folder must be unique
    post_unique: bool = True    # post_folder must be unique (within same artist)
    file_unique: bool = True    # file must be unique (within same post)


# ==================== Validation Data Structure ====================

@dataclass
class ValidationFileData:
    """File data for validation"""
    name: str
    idx: int


@dataclass
class ValidationPostData:
    """Post data for validation"""
    id: str
    user: str
    service: str
    title: str
    published: str
    files: List[ValidationFileData]


@dataclass
class ValidationConfig:
    """Validation configuration (global or per-artist merged)"""
    download_dir: str
    artist_folder_template: str
    post_folder_template: str
    file_template: str
    date_format: str
    rename_images_only: bool
    image_extensions: set


@dataclass
class ValidationArtistData:
    """Artist data for validation with merged config"""
    id: str
    service: str
    name: str
    alias: str
    user_id: str
    last_date: str
    posts: List[ValidationPostData]
    config: ValidationConfig  # Merged config (global + artist overrides)


@dataclass
class ValidationData:
    """Complete validation data structure: Artists -> Posts -> Files

    Each artist has its own config (global config merged with artist-specific overrides).
    """
    artists: List[ValidationArtistData]


# ==================== Scheduler Models ====================

class TaskType:
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class TaskStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadTask:
    artist_id: str
    from_date: Optional[str] = None
    until_date: Optional[str] = None
    task_type: str = TaskType.MANUAL
    status: str = field(default=TaskStatus.QUEUED)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional['DownloadArtistResult'] = None
    error: Optional[str] = None

    def __eq__(self, other):
        if not isinstance(other, DownloadTask):
            return False
        return (
            self.artist_id == other.artist_id
            and self.from_date == other.from_date
            and self.until_date == other.until_date
        )

    def __hash__(self):
        return hash((self.artist_id, self.from_date, self.until_date))


@dataclass
class QueueStatus:
    queued: int
    running: int
    completed: int


# ==================== Migration Models ====================

@dataclass
class MigrationConfig:
    """Configuration for migration operations"""
    download_dir: str
    artist_folder_template: str
    post_folder_template: str
    file_template: str
    date_format: str
    rename_images_only: bool
    image_extensions: set


class MigrationType:
    """Migration type enum"""
    POST = "post"  # Migrate post folders
    FILE = "file"  # Migrate files within posts


@dataclass
class MigrationPlan:
    """Migration plan result"""
    migration_type: str  # "post" or "file"
    total_items: int  # Total posts or files
    mappings: List[tuple]  # [(old_path, new_path, item_id)]
    conflicts: List[tuple]  # [(path, [ids])]
    skipped: List[tuple]  # [(item_id, reason)]
    success_count: int
    conflict_count: int
    skipped_count: int

    @staticmethod
    def empty(migration_type: str) -> 'MigrationPlan':
        """Create empty plan"""
        return MigrationPlan(
            migration_type=migration_type,
            total_items=0,
            mappings=[],
            conflicts=[],
            skipped=[],
            success_count=0,
            conflict_count=0,
            skipped_count=0
        )


@dataclass
class MigrationResult:
    """Migration execution result"""
    migration_type: str
    total: int
    success: int
    failed: List[tuple]  # [(old_path, new_path, item_id, error)]
