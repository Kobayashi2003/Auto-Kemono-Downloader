import inspect
import os
from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from .api import API
from .cache import Cache
from .downloader import Downloader
from .editor import edit_json
from .logger import Logger
from .migrator import Migrator
from .models import Artist, MigrationConfig, ValidationLevel
from .scheduler import Scheduler
from .storage import Storage
from .validator import Validator


# ============================================================================
# Classes
# ============================================================================

class CLIContext:
    """CLI context containing all dependencies"""

    def __init__(self, storage: Storage, scheduler: Scheduler, logger: Logger,
                 cache: Cache, api: API, downloader: Downloader, migrator: Migrator, validator: Validator):
        self.logger = logger
        self.api = api
        self.cache = cache
        self.storage = storage
        self.downloader = downloader
        self.scheduler = scheduler
        self.migrator = migrator
        self.validator = validator


class CommandCompleter(Completer):
    """Command completer for CLI"""

    def __init__(self, commands):
        self.commands = sorted(commands)

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lower()

        # Only complete command part (before ':')
        if ':' in text:
            return

        if not text:
            # Show all commands when empty
            for cmd in self.commands:
                yield Completion(cmd, start_position=0, display=cmd)
        else:
            # Fuzzy match
            for cmd in self.commands:
                if text in cmd:
                    yield Completion(cmd, start_position=-len(text), display=cmd)


class ArtistCompleter(Completer):
    """Custom completer for artist selection with fuzzy matching"""

    def __init__(self, ctx: CLIContext, filter_func=None):
        self.ctx = ctx
        self.filter_func = filter_func
        self.artists = get_artists(ctx, filter_func)
        # Build completion options: each artist has one entry with multiple search keys
        self.completions = []
        for i, artist in enumerate(self.artists, 1):
            # Build search keys: number, name, id, alias (if exists)
            search_keys = [
                str(i),
                artist.name.lower(),
                artist.id.lower()
            ]
            if artist.alias:
                search_keys.append(artist.alias.lower())

            # Build display text with all info
            if artist.alias:
                display = f"{i}. {artist.alias} ({artist.name}) [{artist.id}]"
            else:
                display = f"{i}. {artist.name} [{artist.id}]"

            self.completions.append((search_keys, display, artist))

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lower()

        if not text:
            # Show all when empty
            for i, artist in enumerate(self.artists[:10], 1):  # Limit to first 10
                stats = self.ctx.cache.stats(artist.id)
                status = "DONE" if artist.completed else "IGNORE" if artist.ignore else "Active"
                display = f"{i}. [{status:6}] [{stats['done']}/{stats['total']}] {artist.display_name()}"
                yield Completion(str(i), start_position=0, display=display)
        else:
            # Fuzzy search - check if text matches any search key
            seen = set()
            for search_keys, display, artist in self.completions:
                # Check if text is in any of the search keys
                if any(text in key for key in search_keys):
                    if display not in seen:
                        seen.add(display)
                        yield Completion(artist.id, start_position=-len(text), display=display)


# ============================================================================
# Helper Functions
# ============================================================================

def colorize_artist(text: str, artist: Artist, ctx: CLIContext) -> str:
    """Colorize text based on artist status"""
    if artist.completed:
        return f"\033[92m{text}\033[0m"  # Green
    elif artist.ignore:
        return f"\033[90m{text}\033[0m"  # Gray
    stats = ctx.cache.stats(artist.id)
    if stats['total'] == 0 or stats['pending'] > 0 or stats['failed'] > 0:
        return f"\033[91m{text}\033[0m"  # Red
    return text


def get_artists(ctx: CLIContext, filter_func=None, sort_by='name') -> List[Artist]:
    """Get filtered and sorted artists"""
    artists = ctx.storage.get_artists()

    if filter_func:
        artists = [a for a in artists if filter_func(a)]

    if sort_by == 'name':
        artists.sort(key=lambda a: a.display_name().lower())
    elif sort_by == 'status':
        def status_key(a):
            priority = 2 if a.completed else 1 if a.ignore else 0
            return (priority, a.display_name().lower())
        artists.sort(key=status_key)
    elif sort_by == 'posts':
        artists.sort(key=lambda a: ctx.cache.stats(a.id)['total'], reverse=True)
    elif sort_by == 'recent':
        artists.sort(key=lambda a: a.last_date or '', reverse=True)

    return artists


def display_artist_list(ctx: CLIContext, filter_func=None, sort_by='name', numbered: bool = False):
    """Display artist list"""
    artists = get_artists(ctx, filter_func, sort_by)

    print("\nArtists:")
    print("-" * 80)
    for i, artist in enumerate(artists, 1):
        status = "DONE" if artist.completed else "IGNORE" if artist.ignore else "Active"
        last = artist.last_date or "All posts"
        stats = ctx.cache.stats(artist.id)
        cache_info = f"{stats['done']}/{stats['total']} done" if stats['total'] > 0 else "No cache"

        if numbered:
            line = f"{i:3}. [{status:6}] {last:19} {cache_info:15} - {artist.display_name()}"
        else:
            line = f"[{status:6}] {last:19} {cache_info:15} - {artist.display_name()}"

        print(colorize_artist(line, artist, ctx))
    print("-" * 80)

    return artists


def find_artist(user_input: str, ctx: CLIContext, filter_func=None) -> tuple[Optional[Artist], Optional[callable]]:
    """Find artist by input, returns (exact_match, new_filter_for_matches)"""
    artists = get_artists(ctx, filter_func)

    # Try number
    try:
        idx = int(user_input) - 1
        if 0 <= idx < len(artists):
            return (artists[idx], None)
    except ValueError:
        pass

    # Try exact ID
    user_lower = user_input.lower()
    for artist in artists:
        if user_lower == artist.id.lower():
            return (artist, None)

    # Fuzzy search
    matches = [
        a for a in artists
        if user_lower in a.id.lower() or
           user_lower in a.display_name().lower() or
           (a.alias and user_lower in a.alias.lower())
    ]

    if not matches:
        return (None, None)

    if len(matches) == 1:
        return (matches[0], None)

    # Multiple matches - create filter for them
    match_ids = {a.id for a in matches}
    new_filter = lambda a: a.id in match_ids
    return (None, new_filter)


def prompt_selection(ctx: CLIContext, filter_func=None) -> Optional[Artist]:
    """Prompt userto select an artist"""
    try:
        user_input = prompt("> ", completer=ArtistCompleter(ctx, filter_func)).strip()
        if not user_input:
            return None

        exact, new_filter = find_artist(user_input, ctx, filter_func)

        if exact:
            print(f"Selected: {exact.display_name()}")
            return exact

        if new_filter is None:
            print(f"No artist found matching '{user_input}'")
            return None

        # Multiple matches - display and recurse
        match_count = len(get_artists(ctx, new_filter))
        print(f"\nFound {match_count} matches:")
        display_artist_list(ctx, new_filter, numbered=True)
        return prompt_selection(ctx, new_filter)

    except (KeyboardInterrupt, EOFError):
        print("\nCancelled")
        return None


def select_artist(ctx: CLIContext, filter_func=None, sort_by='name') -> Optional[Artist]:
    """Select artist with auto-completion and fuzzy search

    Input: number/name/ID, Tab for auto-completion, Ctrl+C to cancel
    """
    artists = display_artist_list(ctx, filter_func, sort_by, numbered=True)

    if not artists:
        print("No artists found")
        return None

    print("Enter: number, name, or ID (Tab for auto-completion, Ctrl+C to cancel)")
    return prompt_selection(ctx, filter_func)


# ============================================================================
# Help Commands
# ============================================================================

def cmd_help(ctx: CLIContext = None):
    """Display help"""
    print("\nAvailable commands:")
    print()
    print("Artist Management:")
    print("  add                    - Add a new artist")
    print("  remove                 - Remove an artist")
    print("  list                   - List all artists")
    print("                           Parameters: sort_by=name|status|posts|recent")
    print("                           Example: list:sort_by=status")
    print("  ignore                 - Ignore an artist (skip in scheduled tasks)")
    print("  unignore               - Unignore an artist (include in scheduled tasks)")
    print("  complete               - Mark an artist as completed (skip all downloads)")
    print("  uncomplete             - Mark an artist as not completed (resume downloads)")
    print()
    print("Download & Check:")
    print("  check                  - Check an artist for updates")
    print("  check-from             - Check from specific date")
    print("  check-until            - Check until specific date")
    print("  check-range            - Check date range")
    print("  check-all              - Check all artists")
    print("  check-undone           - Check an artist with undone posts")
    print("  check-all-undone       - Check all artists with undone posts")
    print()
    print("Cache Management:")
    print("  update-cache-basic     - Update basic post info")
    print("  update-all-basic       - Update all basic")
    print("  update-cache-full      - Update full post info")
    print("  update-all-full        - Update all full")
    print("  reset                  - Reset posts after last_date")
    print("  reset-all              - Reset all posts")
    print("  list-undone            - List undone posts")
    print("  list-all-undone        - List all undone")
    print("  dedupe                 - Remove duplicate posts for an artist")
    print("  dedupe-all             - Remove duplicate posts for all artists")
    print()
    print("Task Management:")
    print("  tasks                  - List active and queued tasks")
    print("  cancel-all             - Cancel all queued and running tasks")
    print()
    print("Validation:")
    print("  validate               - Validate path conflicts for an artist")
    print("  validate-all           - Validate path conflicts for all artists")
    print()
    print("Migration:")
    print("  migrate-posts          - Migrate post folders (template changed)")
    print("  migrate-files          - Migrate files within posts (file template changed)")
    print()
    print("Configuration:")
    print("  config-artist          - Edit artist-specific configuration")
    print("  config-global          - Edit global configuration")
    print("  config-validation      - Edit validation ignore configuration")
    print()
    print("Other:")
    print("  help                   - Show this help")
    print("  clear                  - Clear screen")
    print("  exit                   - Exit program")
    print()
    print("Command Parameters:")
    print("  Format: command:param1=value1,param2=value2")
    print("  Example: list:sort_by=status")
    print()


# ============================================================================
# Artist Management Commands
# ============================================================================

def cmd_add_artist(ctx: CLIContext):
    """Add artist"""
    print("\nAdd Artist")
    print("-" * 40)

    url = input("Artist URL: ").strip()
    if not url:
        print("URL required")
        return

    parts = url.rstrip('/').split('/')
    if len(parts) < 5:
        print("Invalid URL format")
        return

    service = parts[-3]
    user_id = parts[-1]

    # Try to fetch artist name from profile
    name = None
    try:
        print("Fetching artist profile...")
        profile = ctx.api.get_profile(service, user_id)
        if profile and profile.get('name'):
            name = profile['name']
            print(f"Found artist name: {name}")
    except Exception as e:
        print(f"Could not fetch profile: {e}")

    if not name:
        name = input("Artist name: ").strip()

    alias = input("Alias (optional): ").strip()

    print("\nLast date (YYYY-MM-DDTHH:MM:SS):")
    print("Posts before this date will be marked as done (skip download)")
    print("Leave empty to download all posts")
    last_date = input("Last date: ").strip()

    if last_date:
        try:
            datetime.fromisoformat(last_date)
        except ValueError:
            print("Invalid date format")
            return

    artist_id = f"{service}_{user_id}"

    if ctx.storage.get_artist(artist_id):
        print(f"Artist {artist_id} already exists")
        return

    artist = Artist(
        id=artist_id,
        service=service,
        user_id=user_id,
        name=name or user_id,
        url=url,
        alias=alias,
        last_date=last_date or None
    )

    ctx.storage.save_artist(artist)
    ctx.logger.info(f"Added artist: {artist.display_name()}")
    print(f"Added: {artist.display_name()}")
    if last_date:
        print(f"Posts before {last_date} will be skipped")


def cmd_remove_artist(ctx: CLIContext):
    """Remove artist"""
    artist = select_artist(ctx)
    if not artist:
        return

    confirm = input(f"\nAre you sure you want to remove {artist.display_name()}? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return
    ctx.storage.remove_artist(artist.id)
    ctx.logger.info(f"Removed artist: {artist.display_name()}")
    print(f"Removed: {artist.display_name()}")


def cmd_list_artists(ctx: CLIContext, sort_by='name'):
    """List all artists

    Args:
        sort_by: Sort method ('name', 'status', 'posts', 'recent')
    """
    artists = display_artist_list(ctx, filter_func=None, sort_by=sort_by, numbered=False)

    if not artists:
        print("No artists found")
        return

    print(f"Total: {len(artists)} artists (sorted by: {sort_by})")
    print()


def cmd_ignore_artist(ctx: CLIContext):
    """Ignore artist"""
    artist = select_artist(ctx, filter_func=lambda a: not a.ignore)
    if not artist:
        return

    artist.ignore = True
    ctx.storage.save_artist(artist)
    print(f"Set ignore flag for: {artist.display_name()}")
    print("This artist will be skipped by scheduled tasks")


def cmd_unignore_artist(ctx: CLIContext):
    """Unignore artist"""
    artist = select_artist(ctx, filter_func=lambda a: a.ignore)
    if not artist:
        return

    artist.ignore = False
    ctx.storage.save_artist(artist)
    print(f"Removed ignore flag for: {artist.display_name()}")
    print("This artist will be included in scheduled tasks")


def cmd_complete_artist(ctx: CLIContext):
    """Mark as completed"""
    artist = select_artist(ctx, filter_func=lambda a: not a.completed)
    if not artist:
        return

    artist.completed = True
    ctx.storage.save_artist(artist)
    print(f"Marked as completed: {artist.display_name()}")
    print("This artist will be skipped in all downloads (manual and scheduled)")


def cmd_uncomplete_artist(ctx: CLIContext):
    """Unmark completed"""
    artist = select_artist(ctx, filter_func=lambda a: a.completed)
    if not artist:
        return

    artist.completed = False
    ctx.storage.save_artist(artist)
    print(f"Removed completed flag for: {artist.display_name()}")
    print("This artist will be included in downloads")


# ============================================================================
# Download & Check Commands
# ============================================================================

def cmd_check_artist(ctx: CLIContext):
    """Check artist"""
    artist = select_artist(ctx)
    if artist:
        print(f"Queued: {artist.display_name()}")
        ctx.scheduler.queue_manual(artist.id)


def cmd_check_all_artists(ctx: CLIContext):
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    active_artists = [a for a in artists if not a.ignore and not a.completed]
    if not active_artists:
        print("No active artists to check")
        return

    added = ctx.scheduler.queue_batch([a.id for a in active_artists])
    print(f"\nQueued {added} artists for download")
    print("Use 'tasks' to view queue status")


def cmd_check_undone(ctx: CLIContext):
    """Check artist with undone posts"""
    artist = select_artist(ctx, filter_func=lambda a: len(ctx.cache.get_undone(a.id)) > 0 or ctx.cache.stats(a.id)['total'] == 0)
    if not artist:
        return

    undone_posts = ctx.cache.get_undone(artist.id)
    if not undone_posts:
        print(f"\n{artist.display_name()}: No undone posts to check")
        return

    print(f"\nQueued: {artist.display_name()} with {len(undone_posts)} undone posts")
    ctx.scheduler.queue_manual(artist.id)


def cmd_check_all_undone(ctx: CLIContext):
    """Check all artists with undone posts"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    active_artists = [a for a in artists if not a.ignore and not a.completed]
    artists_with_undone = [a for a in active_artists if len(ctx.cache.get_undone(a.id)) > 0 or ctx.cache.stats(a.id)['total'] == 0]

    if not artists_with_undone:
        print("No active artists with undone posts to check")
        return

    added = ctx.scheduler.queue_batch([a.id for a in artists_with_undone])
    print(f"\nQueued {added} artists with undone posts for download")
    print("Use 'tasks' to view queue status")


def cmd_check_from_date(ctx: CLIContext):
    """Check from date"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nCurrent last_date: {artist.last_date or 'None'}")
    print("Enter starting date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS):")
    print("Leave empty to check from beginning")

    date_input = input("From date: ").strip()

    from_date = None
    if date_input:
        if 'T' not in date_input:
            date_input = f"{date_input}T00:00:00"
        try:
            datetime.fromisoformat(date_input)
            from_date = date_input
        except ValueError:
            print("Invalid date format")
            return
    else:
        from_date = ""

    print(f"Queued: {artist.display_name()} from {from_date or 'beginning'}")
    ctx.scheduler.queue_manual(artist.id, from_date, None)


def cmd_check_until_date(ctx: CLIContext):
    """Check until date"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nCurrent last_date: {artist.last_date or 'None'}")
    print("Enter ending date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS):")

    date_input = input("Until date: ").strip()
    if not date_input:
        print("Ending date required")
        return

    if 'T' not in date_input:
        date_input = f"{date_input}T23:59:59"

    try:
        datetime.fromisoformat(date_input)
        until_date = date_input
    except ValueError:
        print("Invalid date format")
        return

    print(f"Queued: {artist.display_name()} until {until_date}")
    ctx.scheduler.queue_manual(artist.id, None, until_date)


def cmd_check_date_range(ctx: CLIContext):
    """Check date range"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nCurrent last_date: {artist.last_date or 'None'}")

    print("Enter starting date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS):")
    print("Leave empty to start from beginning")
    from_input = input("From date: ").strip()

    from_date = None
    if from_input:
        if 'T' not in from_input:
            from_input = f"{from_input}T00:00:00"
        try:
            datetime.fromisoformat(from_input)
            from_date = from_input
        except ValueError:
            print("Invalid date format")
            return
    else:
        from_date = ""

    print("Enter ending date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS):")
    until_input = input("Until date: ").strip()
    if not until_input:
        print("Ending date required")
        return

    if 'T' not in until_input:
        until_input = f"{until_input}T23:59:59"

    try:
        datetime.fromisoformat(until_input)
        until_date = until_input
    except ValueError:
        print("Invalid date format")
        return

    if from_date and from_date >= until_date:
        print("Starting date must be before ending date")
        return

    print(f"Queued: {artist.display_name()} from {from_date or 'beginning'} to {until_date}")
    ctx.scheduler.queue_manual(artist.id, from_date, until_date)


# ============================================================================
# Cache Management Commands
# ============================================================================

def cmd_update_cache_basic(ctx: CLIContext):
    """Update basic cache"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nUpdating basic post info for: {artist.display_name()}")
    try:
        updated = ctx.downloader.update_posts_basic(artist)
        if updated:
            print("✓ Cache updated successfully")
        else:
            print("No new posts found")
    except Exception as e:
        print(f"✗ Failed to update cache: {e}")


def cmd_update_all_basic(ctx: CLIContext):
    """Update all basic cache"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    active_artists = [a for a in artists if not a.ignore and not a.completed]
    if not active_artists:
        print("No active artists to update")
        return

    print(f"\nUpdating basic post info for {len(active_artists)} artists...")
    print("This may take a while...\n")

    success_count = 0
    failed_count = 0

    for artist in active_artists:
        try:
            updated = ctx.downloader.update_posts_basic(artist)
            if updated:
                success_count += 1
                print(f"✓ {artist.display_name()}")
            else:
                print(f"- {artist.display_name()} (no new posts)")
        except Exception as e:
            failed_count += 1
            print(f"✗ {artist.display_name()}: {e}")

    print(f"\n{'='*60}")
    print(f"Completed: {success_count} successful, {failed_count} failed")
    print(f"{'='*60}\n")


def cmd_update_cache_full(ctx: CLIContext):
    """Update full cache"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nUpdating full post info for: {artist.display_name()}")
    print("This will fetch complete data for all posts (may take a while)...")

    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    try:
        updated_count = ctx.downloader.update_posts_full(artist)
        print(f"✓ Updated {updated_count} posts with full information")
    except Exception as e:
        print(f"✗ Failed to update: {e}")


def cmd_update_all_full(ctx: CLIContext):
    """Update all full cache"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    active_artists = [a for a in artists if not a.ignore and not a.completed]
    if not active_artists:
        print("No active artists found")
        return

    print(f"\nUpdating full post info for {len(active_artists)} artists...")
    print("This will fetch complete data for all posts (may take a very long time)...")

    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    success_count = 0
    failed_count = 0
    total_updated = 0

    for artist in active_artists:
        try:
            updated_count = ctx.downloader.update_posts_full(artist)
            if updated_count > 0:
                success_count += 1
                total_updated += updated_count
                print(f"✓ {artist.display_name()}: {updated_count} posts")
            else:
                print(f"- {artist.display_name()} (no posts to update)")
        except Exception as e:
            failed_count += 1
            print(f"✗ {artist.display_name()}: {e}")

    print(f"\n{'='*60}")
    print(f"Completed: {success_count} successful, {failed_count} failed")
    print(f"Total posts updated: {total_updated}")
    print(f"{'='*60}\n")


def cmd_reset_artist(ctx: CLIContext, last_date: str = ""):
    """Reset artist posts"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\n{artist.display_name()} - Reset Posts")
    print("-" * 80)

    last_date = None if last_date.lower() == "none" else (last_date or artist.last_date)

    if not last_date:
        print("No last_date set - will reset ALL posts to undone")
        confirm = input("Continue? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Cancelled")
            return
        count = ctx.cache.reset_after_date(artist.id, None)
        print(f"Reset {count} posts to undone (all)")
    else:
        print(f"Current last_date: {last_date}")
        print(f"Will reset posts AFTER {last_date} to undone")
        confirm = input("Continue? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Cancelled")
            return
        count = ctx.cache.reset_after_date(artist.id, last_date)
        print(f"Reset {count} posts to undone")

    if count > 0:
        ctx.logger.info(f"{artist.display_name()}: Reset {count} posts to undone")


def cmd_reset_all_artists(ctx: CLIContext):
    """Reset all posts"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    artists_with_date = [a for a in artists if a.last_date]
    artists_without_date = [a for a in artists if not a.last_date]

    print(f"\nReset Posts for All Artists")
    print("-" * 80)
    if artists_with_date:
        print(f"  With last_date: {len(artists_with_date)} (reset posts after last_date)")
    if artists_without_date:
        print(f"  Without last_date: {len(artists_without_date)} (reset ALL posts)")

    confirm = input("\nContinue? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    total_reset = 0
    for artist in artists_with_date:
        count = ctx.cache.reset_after_date(artist.id, artist.last_date)
        if count > 0:
            ctx.logger.info(f"{artist.display_name()}: Reset {count} posts")
            print(f"{artist.display_name()}: {count} posts")
            total_reset += count

    for artist in artists_without_date:
        count = ctx.cache.reset_after_date(artist.id, None)
        if count > 0:
            ctx.logger.info(f"{artist.display_name()}: Reset {count} posts (all)")
            print(f"{artist.display_name()}: {count} posts (all)")
            total_reset += count

    print(f"\nTotal: {total_reset} posts reset")


def cmd_list_undone(ctx: CLIContext):
    """List undone posts"""
    artist = select_artist(ctx)
    if not artist:
        return

    undone_posts = ctx.cache.get_undone(artist.id)
    if not undone_posts:
        print(f"\n{artist.display_name()}: No undone posts")
        return

    print(f"\n{artist.display_name()} - Undone Posts ({len(undone_posts)}):")
    print("-" * 80)

    for post in undone_posts:
        status = "Not done" if not post.done else f"Failed ({len(post.failed_files)} files)"
        print(f"\nPost ID: {post.id}")
        print(f"Title: {post.title}")
        print(f"Published: {post.published}")
        print(f"Status: {status}")
        if post.failed_files:
            print(f"Failed files:")
            for file in post.failed_files:
                print(f"  - {file}")
    print()


def cmd_list_all_undone(ctx: CLIContext):
    """List all undone posts"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    total_undone = 0
    artists_with_undone = []

    for artist in artists:
        undone_posts = ctx.cache.get_undone(artist.id)
        if undone_posts:
            artists_with_undone.append((artist, undone_posts))
            total_undone += len(undone_posts)

    if not artists_with_undone:
        print("\nNo undone posts found")
        return

    print(f"Undone Posts Summary ({total_undone} posts across {len(artists_with_undone)} artists):")
    print("=" * 80)

    for artist, undone_posts in artists_with_undone:
        print(f"\n{artist.display_name()} - {len(undone_posts)} undone posts:")
        print("-" * 80)

        for post in undone_posts:
            status = "Not done" if not post.done else f"Failed ({len(post.failed_files)} files)"
            print(f"  [{post.published[:10]}] {post.title[:50]} - {status}")
            if post.failed_files and len(post.failed_files) <= 3:
                print(f"    Failed files: {', '.join(post.failed_files)}")
            elif post.failed_files:
                print(f"    Failed files: {', '.join(post.failed_files[:3])} ... and {len(post.failed_files) - 3} more")
    print()


def cmd_dedupe_artist(ctx: CLIContext):
    """Remove duplicate posts for an artist"""
    artist = select_artist(ctx)
    if not artist:
        return

    posts = ctx.cache.load_posts(artist.id)
    if not posts:
        print(f"\n{artist.display_name()}: No cached posts found")
        return

    print(f"\n{artist.display_name()} - Removing duplicate posts...")
    print("-" * 80)
    print(f"Total posts before: {len(posts)}")

    duplicate_count = ctx.cache.deduplicate_posts(artist.id)

    if duplicate_count == 0:
        print("✓ No duplicate posts found")
    else:
        posts_after = ctx.cache.load_posts(artist.id)
        print(f"✗ Found and removed {duplicate_count} duplicate posts")
        print(f"Total posts after: {len(posts_after)}")
        ctx.logger.info(f"{artist.display_name()}: Removed {duplicate_count} duplicate posts")

    print()


def cmd_dedupe_all_artists(ctx: CLIContext):
    """Remove duplicate posts for all artists"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    print(f"\nRemoving duplicate posts for {len(artists)} artists...")
    print("=" * 80)

    total_duplicates = 0
    artists_with_duplicates = []

    for artist in artists:
        posts = ctx.cache.load_posts(artist.id)
        if not posts:
            continue

        duplicate_count = ctx.cache.deduplicate_posts(artist.id)
        if duplicate_count > 0:
            artists_with_duplicates.append((artist, duplicate_count))
            total_duplicates += duplicate_count

    if not artists_with_duplicates:
        print("\n✓ No duplicate posts found")
    else:
        print(f"\n✗ Found and removed duplicates from {len(artists_with_duplicates)} artists:")
        print("-" * 80)

        for artist, duplicate_count in artists_with_duplicates:
            print(f"  {artist.display_name()}: {duplicate_count} duplicates removed")
            ctx.logger.info(f"{artist.display_name()}: Removed {duplicate_count} duplicate posts")

        print(f"\n{'='*80}")
        print(f"Total duplicates removed: {total_duplicates}")

    print()


# ============================================================================
# Task Management Commands
# ============================================================================

def cmd_tasks(ctx: CLIContext):
    status = ctx.scheduler.get_queue_status()
    active_tasks = ctx.scheduler.list_active_tasks()
    queued_tasks = ctx.scheduler.list_queued_tasks()

    print("\n" + "=" * 80)
    print("TASK QUEUE STATUS")
    print("=" * 80)
    print(f"  Queued:    {status.queued:>3}")
    print(f"  Running:   {status.running:>3}")
    print(f"  Completed: {status.completed:>3}")
    print()

    if active_tasks:
        print("-" * 80)
        print(f"RUNNING TASKS ({len(active_tasks)})")
        print("-" * 80)
        print(f"{'Type':<10} {'Status':<10} {'Elapsed':<10} Artist")
        print("-" * 80)
        for task in active_tasks:
            elapsed = ""
            if task.started_at:
                seconds = (datetime.now() - task.started_at).seconds
                if seconds < 60:
                    elapsed = f"{seconds}s"
                elif seconds < 3600:
                    elapsed = f"{seconds // 60}m {seconds % 60}s"
                else:
                    elapsed = f"{seconds // 3600}h {(seconds % 3600) // 60}m"

            artist = ctx.storage.get_artist(task.artist_id)
            name = artist.display_name() if artist else task.artist_id
            print(f"{task.task_type:<10} {task.status:<10} {elapsed:<10} {name}")
        print()

    if queued_tasks and len(queued_tasks) > 0:
        print("-" * 80)
        print(f"QUEUED TASKS ({len(queued_tasks)})")
        print("-" * 80)
        print(f"{'Type':<10} Artist")
        print("-" * 80)
        for task in queued_tasks[:10]:
            artist = ctx.storage.get_artist(task.artist_id)
            name = artist.display_name() if artist else task.artist_id
            print(f"{task.task_type:<10} {name}")
        if len(queued_tasks) > 10:
            print(f"\n... and {len(queued_tasks) - 10} more tasks")
        print()

    print("=" * 80)


def cmd_cancel_all(ctx: CLIContext):
    """Cancel all queued and running tasks"""
    status = ctx.scheduler.get_queue_status()

    if status.queued == 0 and status.running == 0:
        print("No tasks to cancel")
        return

    print(f"\nCurrent tasks:")
    print(f"  Queued:  {status.queued}")
    print(f"  Running: {status.running}")
    print()

    confirm = input("Cancel all tasks? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    print("\nCancelling all tasks...")
    active_count = ctx.scheduler.cancel_all_tasks()

    print(f"✓ Cancelled {status.queued} queued tasks")
    print(f"✓ Stopped {active_count} running tasks")
    print("\nNote: Running downloads will stop at the next safe point")


# ============================================================================
# Validation Commands
# ============================================================================

def cmd_validate_artist(ctx: CLIContext):
    """Validate artist paths"""
    artist = select_artist(ctx)
    if not artist:
        return

    posts = ctx.cache.load_posts(artist.id)
    if not posts:
        print(f"\n{artist.display_name()}: No cached posts found")
        print("Run 'update-cache-basic' or 'update-cache-full' first to fetch posts")
        return

    config = ctx.storage.load_config()

    print(f"\n{artist.display_name()} - Validating paths...")
    print("-" * 80)

    print("\nValidation level:")
    print("1. Artist folder only")
    print("2. Artist + Post folders")
    print("3. Full paths (Artist + Post + Files) [default]")
    level_input = input("Select level (1-3, default=3): ").strip()

    if level_input == "1":
        level = ValidationLevel(artist_unique=True, post_unique=False, file_unique=False)
    elif level_input == "2":
        level = ValidationLevel(artist_unique=True, post_unique=True, file_unique=False)
    else:
        level = ValidationLevel(artist_unique=True, post_unique=True, file_unique=True)

    validation_data = Validator.build_validation_data([(artist, posts)], config)

    if not validation_data.artists:
        print("No files found in posts")
        return

    total_files = sum(
        len(post.files)
        for artist_data in validation_data.artists
        for post in artist_data.posts
    )

    # Validate with automatic ignore management
    conflicts, filtered_count = ctx.validator.validate_full_paths(validation_data, level)
    ignore_file = ctx.validator.get_ignore_file_path()

    if filtered_count > 0:
        print(f"Filtered {filtered_count} ignored conflicts")

    if not conflicts:
        print("\n✓ No conflicts found!")
        print(f"Total files checked: {total_files}")
        print(f"\nValidation ignore file updated: {ignore_file}")
    else:
        print(f"\n✗ Found {len(conflicts)} conflicts:")
        print("-" * 80)

        for path, ids in conflicts:
            print(f"\nPath: {path}")
            print(f"Conflicts: {len(ids)} items")
            print(f"IDs:")
            for id_str in ids:
                print(f"  - {id_str}")

        print("-" * 80)
        print(f"Total conflicts: {len(conflicts)}")
        print(f"Total files checked: {total_files}")

        print(f"\nValidation ignore file updated: {ignore_file}")
        print("Edit the 'ignores' array to mark paths you want to ignore")

    print()


def cmd_validate_all_artists(ctx: CLIContext):
    """Validate all paths"""
    artists = ctx.storage.get_artists()
    if not artists:
        print("No artists found")
        return

    config = ctx.storage.load_config()

    print(f"\nValidating paths for {len(artists)} artists...")
    print("-" * 80)

    print("\nValidation level:")
    print("1. Artist folder only")
    print("2. Artist + Post folders")
    print("3. Full paths (Artist + Post + Files) [default]")
    level_input = input("Select level (1-3, default=3): ").strip()

    if level_input == "1":
        level = ValidationLevel(artist_unique=True, post_unique=False, file_unique=False)
    elif level_input == "2":
        level = ValidationLevel(artist_unique=True, post_unique=True, file_unique=False)
    else:
        level = ValidationLevel(artist_unique=True, post_unique=True, file_unique=True)

    artists_with_posts = []
    for artist in artists:
        if artist.ignore:
            continue
        posts = ctx.cache.load_posts(artist.id)
        if posts:
            artists_with_posts.append((artist, posts))

    if not artists_with_posts:
        print("\nNo files found in cached posts")
        print("Run 'update-all-basic' or 'update-all-full' first to fetch posts")
        return

    validation_data = Validator.build_validation_data(artists_with_posts, config)

    total_posts = sum(len(a.posts) for a in validation_data.artists)
    total_files = sum(
        len(post.files)
        for artist_data in validation_data.artists
        for post in artist_data.posts
    )

    print(f"\nCollected data:")
    print(f"  Artists with cache: {len(validation_data.artists)}")
    print(f"  Total posts: {total_posts}")
    print(f"  Total files: {total_files}")
    print("\nValidating...")

    # Validate with automatic ignore management
    conflicts, filtered_count = ctx.validator.validate_full_paths(validation_data, level)
    ignore_file = ctx.validator.get_ignore_file_path()

    if filtered_count > 0:
        print(f"Filtered {filtered_count} ignored conflicts")

    # Group conflicts by artist for display
    artist_conflicts = defaultdict(list)
    for path, ids in conflicts:
        if ids:
            artist_id = ids[0].split(':')[0]
            artist_conflicts[artist_id].append((path, ids))

    print("-" * 80)
    if not conflicts:
        print("\n✓ No conflicts found!")
    else:
        print(f"\n✗ Found {len(conflicts)} conflicts across {len(artist_conflicts)} artists")
        print("\nConflicts by artist:")
        print("-" * 80)

        artist_map = {a.id: a for a in artists}
        for artist_id, artist_conflict_list in sorted(artist_conflicts.items(),
                                                      key=lambda x: len(x[1]),
                                                      reverse=True):
            artist = artist_map.get(artist_id)
            artist_name = artist.display_name() if artist else artist_id
            print(f"\n{artist_name} ({artist_id}):")
            print(f"  Conflicts: {len(artist_conflict_list)}")

            for path, ids in artist_conflict_list[:3]:
                print(f"    - {path} ({len(ids)} items)")

            if len(artist_conflict_list) > 3:
                print(f"    ... and {len(artist_conflict_list) - 3} more")

    # Show updated file
    print(f"\n{'='*80}")
    print(f"Validation ignore file updated: {ignore_file}")
    print(f"Updated {len(validation_data.artists)} artists")
    if conflicts:
        print("\nEdit the 'ignores' array for each artist to mark paths you want to ignore")

    print(f"\n{'='*80}")
    print(f"Summary:")
    print(f"  Total conflicts: {len(conflicts)}")
    print(f"  Total files checked: {total_files}")
    print()


# ============================================================================
# Migration Commands
# ============================================================================

def cmd_migrate_posts(ctx: CLIContext):
    """Migrate post folders"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nMigrate Post Folders: {artist.display_name()}")
    print("-" * 80)
    print("This will migrate post folders based on template changes.")
    print("Only one-to-one mappings will be migrated (conflicts skipped).")
    print()

    config = ctx.storage.load_config()

    print("Current templates:")
    print(f"  Download dir: {config.download_dir}")
    print(f"  Artist:       {artist.config.get('artist_folder_template', config.artist_folder_template)}")
    print(f"  Post:         {artist.config.get('post_folder_template', config.post_folder_template)}")
    print(f"  Date format:  {config.date_format}")
    print()

    print("Enter download_dir (or press Enter to use current):")
    download_dir = input("> ").strip()
    if not download_dir:
        download_dir = config.download_dir

    print("Enter artist_folder_template (or press Enter to use current):")
    artist_template = input("> ").strip()
    if not artist_template:
        artist_template = artist.config.get('artist_folder_template', config.artist_folder_template)

    print("Enter OLD post_folder_template (or press Enter to use current):")
    old_post_template = input("> ").strip()
    if not old_post_template:
        old_post_template = artist.config.get('post_folder_template', config.post_folder_template)

    print("Enter NEW post_folder_template:")
    new_post_template = input("> ").strip()
    if not new_post_template:
        print("New template required")
        return

    print("Enter date_format (or press Enter to use current):")
    date_format = input("> ").strip()
    if not date_format:
        date_format = config.date_format

    old_config = MigrationConfig(
        download_dir=download_dir,
        artist_folder_template=artist_template,
        post_folder_template=old_post_template,
        file_template=config.file_template,
        date_format=date_format,
        rename_images_only=config.rename_images_only,
        image_extensions=config.image_extensions,
    )

    new_config = MigrationConfig(
        download_dir=download_dir,
        artist_folder_template=artist_template,
        post_folder_template=new_post_template,
        file_template=config.file_template,
        date_format=date_format,
        rename_images_only=config.rename_images_only,
        image_extensions=config.image_extensions,
    )

    print("\nGenerating migration plan...")
    plan = ctx.migrator.migrate_posts(artist, old_config, new_config)

    print(f"\n{'='*80}")
    print(f"Migration Plan: {artist.display_name()}")
    print(f"{'='*80}")
    print(f"Total posts: {plan.total_items}")
    print(f"Can migrate: {plan.success_count}")
    print(f"Conflicts: {plan.conflict_count}")
    print(f"Skipped: {plan.skipped_count}")

    if plan.conflicts:
        print(f"\nPath conflicts: {len(plan.conflicts)}")
        for path, ids in plan.conflicts[:3]:
            print(f"  {path} ({len(ids)} posts)")
        if len(plan.conflicts) > 3:
            print(f"  ... and {len(plan.conflicts) - 3} more")

    if plan.skipped:
        skipped_by_reason = {}
        for post_id, reason in plan.skipped:
            skipped_by_reason.setdefault(reason, []).append(post_id)
        print(f"\nSkipped posts:")
        for reason, post_ids in skipped_by_reason.items():
            print(f"  {reason}: {len(post_ids)}")

    if plan.mappings:
        print(f"\nSample mappings (first 3):")
        for old_path, new_path, post_id in plan.mappings[:3]:
            print(f"\n  Post: {post_id}")
            print(f"    From: {old_path}")
            print(f"    To:   {new_path}")

    if plan.success_count == 0:
        print("\n⚠ No posts to migrate")
        return

    print(f"\n{'='*80}")
    confirm = input(f"Migrate {plan.success_count} posts? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    print("\nMigrating...")
    result = ctx.migrator.execute_migration(plan)

    print(f"\n{'='*80}")
    print(f"Migration Results")
    print(f"{'='*80}")
    print(f"Total: {result.total}")
    print(f"Success: {result.success}")
    print(f"Failed: {len(result.failed)}")

    if result.failed:
        print(f"\nFailed migrations:")
        for old_path, new_path, post_id, error in result.failed[:5]:
            print(f"\n  Post: {post_id}")
            print(f"    Error: {error}")
        if len(result.failed) > 5:
            print(f"\n  ... and {len(result.failed) - 5} more failures")

    if result.success == result.total:
        print("\n✓ All migrations completed successfully!")
    elif result.success > 0:
        print(f"\n⚠ Partial success: {result.success}/{result.total} migrated")
    else:
        print("\n✗ Migration failed")

    print()


def cmd_migrate_files(ctx: CLIContext):
    """Migrate files"""
    artist = select_artist(ctx)
    if not artist:
        return

    print(f"\nMigrate Files: {artist.display_name()}")
    print("-" * 80)
    print("This will migrate files within post folders.")
    print("Only one-to-one mappings will be migrated (conflicts skipped).")
    print()

    config = ctx.storage.load_config()

    print("Current templates:")
    print(f"  Download dir:        {config.download_dir}")
    print(f"  Artist:              {artist.config.get('artist_folder_template', config.artist_folder_template)}")
    print(f"  Post:                {artist.config.get('post_folder_template', config.post_folder_template)}")
    print(f"  File:                {artist.config.get('file_template', config.file_template)}")
    print(f"  Date format:         {config.date_format}")
    print(f"  Rename images only:  {config.rename_images_only}")
    print(f"  Image extensions:    {', '.join(config.image_extensions)}")
    print()

    print("Enter download_dir (or press Enter to use current):")
    download_dir = input("> ").strip()
    if not download_dir:
        download_dir = config.download_dir

    print("Enter artist_folder_template (or press Enter to use current):")
    artist_template = input("> ").strip()
    if not artist_template:
        artist_template = artist.config.get('artist_folder_template', config.artist_folder_template)

    print("Enter post_folder_template (or press Enter to use current):")
    post_template = input("> ").strip()
    if not post_template:
        post_template = artist.config.get('post_folder_template', config.post_folder_template)

    print("Enter date_format (or press Enter to use current):")
    date_format = input("> ").strip()
    if not date_format:
        date_format = config.date_format

    print("Enter OLD file_template (or press Enter to use current):")
    old_file_template = input("> ").strip()
    if not old_file_template:
        old_file_template = artist.config.get('file_template', config.file_template)

    print("Enter NEW file_template:")
    new_file_template = input("> ").strip()
    if not new_file_template:
        print("New template required")
        return

    print("Enter rename_images_only (true/false, or press Enter to use current):")
    rename_input = input("> ").strip().lower()
    if rename_input in ['true', 'false']:
        rename_images_only = rename_input == 'true'
    else:
        rename_images_only = config.rename_images_only

    print("Enter image_extensions (comma-separated, or press Enter to use current):")
    print(f"Example: .jpg,.png,.gif")
    ext_input = input("> ").strip()
    if ext_input:
        image_extensions = set(e.strip() for e in ext_input.split(','))
    else:
        image_extensions = config.image_extensions

    old_config = MigrationConfig(
        download_dir=download_dir,
        artist_folder_template=artist_template,
        post_folder_template=post_template,
        file_template=old_file_template,
        date_format=date_format,
        rename_images_only=rename_images_only,
        image_extensions=image_extensions,
    )

    new_config = MigrationConfig(
        download_dir=download_dir,
        artist_folder_template=artist_template,
        post_folder_template=post_template,
        file_template=new_file_template,
        date_format=date_format,
        rename_images_only=rename_images_only,
        image_extensions=image_extensions,
    )

    print("\nGenerating migration plan...")
    plan = ctx.migrator.migrate_files(artist, old_config, new_config)

    print(f"\n{'='*80}")
    print(f"Migration Plan: {artist.display_name()}")
    print(f"{'='*80}")
    print(f"Total files: {plan.total_items}")
    print(f"Can migrate: {plan.success_count}")
    print(f"Conflicts: {plan.conflict_count}")
    print(f"Skipped: {plan.skipped_count}")

    if plan.conflicts:
        print(f"\nPath conflicts: {len(plan.conflicts)}")

    if plan.skipped:
        skipped_by_reason = {}
        for file_key, reason in plan.skipped:
            skipped_by_reason.setdefault(reason, []).append(file_key)
        print(f"\nSkipped files:")
        for reason, file_keys in skipped_by_reason.items():
            print(f"  {reason}: {len(file_keys)}")

    if plan.mappings:
        print(f"\nSample mappings (first 3):")
        for old_path, new_path, file_key in plan.mappings[:3]:
            print(f"\n  File: {file_key}")
            print(f"    From: {old_path}")
            print(f"    To:   {new_path}")

    if plan.success_count == 0:
        print("\n⚠ No files to migrate")
        return

    print(f"\n{'='*80}")
    confirm = input(f"Migrate {plan.success_count} files? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled")
        return

    print("\nMigrating...")
    result = ctx.migrator.execute_migration(plan)

    print(f"\n{'='*80}")
    print(f"Migration Results")
    print(f"{'='*80}")
    print(f"Total: {result.total}")
    print(f"Success: {result.success}")
    print(f"Failed: {len(result.failed)}")

    if result.failed:
        print(f"\nFailed migrations:")
        for old_path, new_path, file_key, error in result.failed[:5]:
            print(f"\n  File: {file_key}")
            print(f"    Error: {error}")
        if len(result.failed) > 5:
            print(f"\n  ... and {len(result.failed) - 5} more failures")

    if result.success == result.total:
        print("\n✓ All migrations completed successfully!")
    elif result.success > 0:
        print(f"\n⚠ Partial success: {result.success}/{result.total} migrated")
    else:
        print("\n✗ Migration failed")

    print()

# ============================================================================
# Configuration Commands
# ============================================================================

def cmd_config_artist(ctx: CLIContext):
    """Edit artist config"""
    artist = select_artist(ctx)
    if not artist:
        return

    # Build editable config
    config_data = {
        "_info": {
            "id": artist.id,
            "name": artist.name,
            "service": artist.service,
            "alias": artist.alias,
        },
        "config": artist.config,
        "filter": artist.filter,
        "timer": artist.timer,
        "ignore": artist.ignore,
        "completed": artist.completed,
        "last_date": artist.last_date,
    }

    # Open editor
    new_config = edit_json(config_data, f"Config: {artist.display_name()}")

    if new_config:
        try:
            # Apply changes (skip _info as it's read-only)
            artist.config = new_config.get("config", {})
            artist.filter = new_config.get("filter", {})
            artist.timer = new_config.get("timer")
            artist.ignore = new_config.get("ignore", False)
            artist.completed = new_config.get("completed", False)
            artist.last_date = new_config.get("last_date")

            ctx.storage.save_artist(artist)
            print(f"✓ Configuration saved for {artist.display_name()}")
        except Exception as e:
            print(f"✗ Failed to save: {e}")
    else:
        print("Cancelled")


def cmd_config_global(ctx: CLIContext):
    """Edit global config"""
    config = ctx.storage.load_config()

    # Build editable config
    config_data = {
        "paths": {
            "cache_dir": config.cache_dir,
            "logs_dir": config.logs_dir,
            "temp_dir": config.temp_dir,
            "download_dir": config.download_dir,
        },
        "templates": {
            "artist_folder_template": config.artist_folder_template,
            "post_folder_template": config.post_folder_template,
            "file_template": config.file_template,
            "date_format": config.date_format,
        },
        "download": {
            "max_retries": config.max_retries,
            "retry_delay": config.retry_delay,
            "request_timeout": config.request_timeout,
        },
        "concurrency": {
            "max_concurrent_artists": config.max_concurrent_artists,
            "max_concurrent_posts": config.max_concurrent_posts,
            "max_concurrent_files": config.max_concurrent_files,
        },
        "behavior": {
            "save_content": config.save_content,
            "save_empty_posts": config.save_empty_posts,
            "rename_images_only": config.rename_images_only,
            "image_extensions": list(config.image_extensions),
        },
        "global_timer": config.global_timer,
        "global_filter": config.global_filter,
    }

    # Open editor
    new_config = edit_json(config_data, "Global Configuration")

    if new_config:
        try:
            # Apply changes
            config.cache_dir = new_config["paths"]["cache_dir"]
            config.logs_dir = new_config["paths"]["logs_dir"]
            config.temp_dir = new_config["paths"]["temp_dir"]
            config.download_dir = new_config["paths"]["download_dir"]

            config.artist_folder_template = new_config["templates"]["artist_folder_template"]
            config.post_folder_template = new_config["templates"]["post_folder_template"]
            config.file_template = new_config["templates"]["file_template"]
            config.date_format = new_config["templates"]["date_format"]

            config.max_retries = new_config["download"]["max_retries"]
            config.retry_delay = new_config["download"]["retry_delay"]
            config.request_timeout = new_config["download"]["request_timeout"]

            config.max_concurrent_artists = new_config["concurrency"]["max_concurrent_artists"]
            config.max_concurrent_posts = new_config["concurrency"]["max_concurrent_posts"]
            config.max_concurrent_files = new_config["concurrency"]["max_concurrent_files"]

            config.save_content = new_config["behavior"]["save_content"]
            config.save_empty_posts = new_config["behavior"]["save_empty_posts"]
            config.rename_images_only = new_config["behavior"]["rename_images_only"]
            config.image_extensions = set(new_config["behavior"]["image_extensions"])

            config.global_timer = new_config.get("global_timer")
            config.global_filter = new_config.get("global_filter", {})

            ctx.storage.save_config(config)
            print("✓ Global configuration saved")
        except Exception as e:
            print(f"✗ Failed to save: {e}")
    else:
        print("Cancelled")


def cmd_config_validation(ctx: CLIContext):
    """Edit validation ignore config"""
    ignore_data = ctx.validator.load_ignore_data()

    if not ignore_data:
        print("\nNo validation ignore data found")
        print("Run 'validate' or 'validate-all' first to generate the file")
        return

    # Open editor
    new_data = edit_json(ignore_data, "Validation Ignore Configuration")

    if new_data:
        try:
            ctx.validator.save_ignore_data(new_data)
            print("✓ Validation ignore configuration saved")
        except Exception as e:
            print(f"✗ Failed to save: {e}")
    else:
        print("Cancelled")


def cmd_clear(ctx: CLIContext = None):
    """Clear screen"""
    os.system('cls' if os.name == 'nt' else 'clear')


def cmd_exit(ctx: CLIContext):
    """Exit program with confirmation"""
    # Check if there are active tasks
    status = ctx.scheduler.get_queue_status()
    if status.running > 0 or status.queued > 0:
        print(f"\n⚠ Warning: {status.running} running and {status.queued} queued tasks")
        confirm = input("Force quit and stop all tasks? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Exit cancelled")
            return

    # Force shutdown
    print("\nShutting down...")
    ctx.downloader.stop()
    ctx.scheduler.stop()
    ctx.logger.info("Shutdown complete")
    os._exit(0)


# ============================================================================
# Command Dispatcher
# ============================================================================

COMMAND_MAP = {
    'help': cmd_help,
    'add': cmd_add_artist,
    'remove': cmd_remove_artist,
    'list': cmd_list_artists,
    'ignore': cmd_ignore_artist,
    'unignore': cmd_unignore_artist,
    'complete': cmd_complete_artist,
    'uncomplete': cmd_uncomplete_artist,
    'check': cmd_check_artist,
    'check-from': cmd_check_from_date,
    'check-until': cmd_check_until_date,
    'check-range': cmd_check_date_range,
    'check-all': cmd_check_all_artists,
    'check-undone': cmd_check_undone,
    'check-all-undone': cmd_check_all_undone,
    'update-cache-basic': cmd_update_cache_basic,
    'update-all-basic': cmd_update_all_basic,
    'update-cache-full': cmd_update_cache_full,
    'update-all-full': cmd_update_all_full,
    'validate': cmd_validate_artist,
    'validate-all': cmd_validate_all_artists,
    'migrate-posts': cmd_migrate_posts,
    'migrate-files': cmd_migrate_files,
    'reset': cmd_reset_artist,
    'reset-all': cmd_reset_all_artists,
    'list-undone': cmd_list_undone,
    'list-all-undone': cmd_list_all_undone,
    'dedupe': cmd_dedupe_artist,
    'dedupe-all': cmd_dedupe_all_artists,
    'tasks': cmd_tasks,
    'cancel-all': cmd_cancel_all,
    'config-artist': cmd_config_artist,
    'config-global': cmd_config_global,
    'config-validation': cmd_config_validation,
    'clear': cmd_clear,
    'exit': cmd_exit,
}


def parse_command(cmd_input: str) -> tuple[str, dict]:
    """Parse command with parameters

    Format: command:param1=value1,param2=value2
    Example: list:sort_by=status

    Returns: (command, params_dict)
    """
    if ':' not in cmd_input:
        return (cmd_input, {})

    parts = cmd_input.split(':', 1)
    command = parts[0].strip()
    params_str = parts[1].strip()

    params = {}
    if params_str:
        for param in params_str.split(','):
            param = param.strip()
            if '=' in param:
                key, value = param.split('=', 1)
                params[key.strip()] = value.strip()

    return (command, params)


def run_cli(ctx: CLIContext):
    """CLI main loop"""
    # Create command completer
    command_completer = CommandCompleter(COMMAND_MAP.keys())

    while True:
        try:
            # Use prompt with command completion
            cmd_input = prompt("> ", completer=command_completer).strip().lower()

            if not cmd_input:
                continue

            command, params = parse_command(cmd_input)
            handler = COMMAND_MAP.get(command)

            if handler:
                # Check if handler accepts the provided parameters
                sig = inspect.signature(handler)
                handler_params = set(sig.parameters.keys()) - {'ctx'}
                if params:
                    # Filter params to only include those the handler accepts
                    valid_params = {k: v for k, v in params.items() if k in handler_params}
                    invalid_params = set(params.keys()) - handler_params

                    if invalid_params:
                        print(f"Warning: Command '{command}' doesn't support parameters: {', '.join(invalid_params)}")

                    handler(ctx, **valid_params)
                else:
                    handler(ctx)
            else:
                print("Unknown command. Type 'help' for available commands.")

        except KeyboardInterrupt:
            # Re-raise to allow proper cleanup in main.py
            raise
        except Exception as e:
            print(f"Error: {e}")


# ============================================================================
# CLI Class - Backward compatibility wrapper
# ============================================================================

class CLI:
    def __init__(self, storage: Storage, scheduler: Scheduler, logger: Logger,
                 cache: Cache, api: API, downloader: Downloader, migrator: Migrator, validator: Validator):
        self.ctx = CLIContext(storage, scheduler, logger, cache, api, downloader, migrator, validator)

    def run(self):
        """Run CLI"""
        run_cli(self.ctx)