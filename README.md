# Auto Kemono Downloader

A simple CLI tool for downloading and managing content from Kemono.cr.

## Features

- **Artist Management** - Add, remove, and organize artists
- **Caching** - Avoid re-downloading existing content
- **Filtering** - Filter by date ranges and status
- **Automatic Downloads** - Schedule periodic updates
- **Concurrent Downloads** - Download multiple files in parallel
- **Proxy Pogol Support** - Convert Clash subscriptions to proxy pool for load balancing
- **Multi-Terminal Support** - Connect multiple terminals to the same instance


## Installation

### Requirements

- Python 3.8+
- pip

### Setup

```bash
# Clone or download the repository
cd auto-kemono-downloader

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Quick Start

### First Launch

```bash
$ python main.py

> help
```

### Basic Workflow

1. **Add an artist**
   ```
   > add
   Artist URL: https://kemono.cr/fanbox/user/12345
   ```

2. **List artists**
   ```
   > list
   > list:sort_by=name
   ```

3. **Download content**
   ```
   > check
   [Select artist from list]
   ```

4. **Check download status**
   ```
   > tasks
   ```

## Command Reference

### Artist Management

| Command      | Description                                     |
| ------------ | ----------------------------------------------- |
| `add`        | Add a new artist                                |
| `remove`     | Remove an artist                                |
| `list`       | List all artists (supports `sort_by` parameter) |
| `ignore`     | Mark artist as ignore                           |
| `unignore`   | Mark artist as unignore                         |
| `complete`   | Mark artist as completed                        |
| `uncomplete` | Mark artist as uncompleted                      |

- **Tips for Using `sort_by`**:
  - `name`: Sort artists alphabetically by name.
  - `status`: Sort artists by their status (active, ignored, completed).
  - `posts`: Sort artists by the number of posts available.
  - `recent`: Sort artists based on the most recent activity since the user's `last_date`.

- **About ignore and complete states**: Artists marked as ignore or complete will be skipped in bulk operations like scheduled downloads, `check-all`, and `update-all`.

### Downloads

| Command       | Description                             |
| ------------- | --------------------------------------- |
| `check`       | Download updates for an artist          |
| `check-all`   | Download updates for all active artists |
| `check-from`  | Download from specific date             |
| `check-until` | Download until specific date            |
| `check-range` | Download within date range              |

- **About update**: When adding an artist, a `last_date` attribute is set to mark all posts before that date as completed. Subsequent cache updates will treat posts with `done` set to false as new updates.

### Task Management

| Command      | Description                         |
| ------------ | ----------------------------------- |
| `tasks`      | View active and queued downloads    |
| `cancel-all` | Cancel all running and queued tasks |

### Cache Management

| Command              | Description                                       |
| -------------------- | ------------------------------------------------- |
| `update-cache-basic` | Update basic post information for one artist      |
| `update-cache-full`  | Update full post information for one artist       |
| `update-all-basic`   | Update basic post information for all artist      |
| `update-all-full`    | Update full post information for all artist       |
| `reset`              | Reset download status for one artist (support `last_date` parameter) |
| `reset-all`          | Reset download status for all artists             |
| `list-incomplete`    | Show incomplete downloads for one artist          |
| `list-incomplete-all`| Show incomplete downloads for all artists         |
| `dedupe`             | Remove duplicate posts from cache for one artist  |
| `dedupe-all`         | Remove duplicate posts from cache for all artists |

- **Tips for Using `last_date` with `reset`**:
  - `reset:last_date=YYYY-MM-DD`: Resets the download status for posts after the specified date.
  - `reset:last_date=None`: Marks all posts as not done, allowing re-download of all content.

### Configuration

| Command             | Description                   |
| ------------------  | ----------------------------- |
| `config-artist`     | Edit artist-specific settings |
| `config-global`     | Edit global configuration     |
| `config-validation` | Edit validation configuration |


### Validation

| `validate`          | Check for path conflicts for one artist  |
| `validate-all`      | Check for path conflicts for all artists |

### Migration

| Command         | Description                            |
| --------------- | -------------------------------------- |
| `migrate-posts` | Migrate post_folders to new structure  |
| `migrate-files` | Migrate files to new structure         |

- **About Validation and Migration**: The downloader supports customizable naming templates for file organization, which can be configured in `config.json` and `artists.json`. The validation commands check for potential path conflicts based on these templates, while migration commands help reorganize files when changing naming conventions.

### Other

| Command | Description       |
| ------- | ----------------- |
| `help`  | Show all commands |
| `clear` | Clear screen      |
| `exit`  | Exit program      |


## Command Parameters

Some commands support parameters using the format `command:param=value`:

```bash
# Sort artists by status
> list:sort_by=status

# Available sort options: name, status, posts, recent
> list:sort_by=recent
```

## Configuration

Configuration files are stored in the `data/` directory:

- `data/config.json` - Global settings
- `data/artists.json` - Artist list and settings
- `data/validation_ignore.json` - Paths to ignore during validation
