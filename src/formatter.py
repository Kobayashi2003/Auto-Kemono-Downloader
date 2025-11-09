import re
from datetime import datetime
from pathlib import Path
from typing import List

from .models import ArtistFolderParams, FileParams, PostFolderParams


class Formatter:
    """Pure path formatter with three levels:
    1. Artist folder: {service}/{name} etc
    2. Post folder: [{published}] {title} etc
    3. File name: {idx} or {name} etc

    Final path: download_dir / artist_folder / post_folder / filename

    All parameters must be explicitly provided by caller.
    """

    # ==================== Level 1: Artist Folder ====================

    @staticmethod
    def format_artist_folder(params: ArtistFolderParams, template: str) -> Path:
        """Format artist folder path"""
        safe_service = Formatter._sanitize(params.service)
        safe_name = Formatter._sanitize(params.name)
        safe_alias = Formatter._sanitize(params.alias) if params.alias else ""
        safe_user_id = Formatter._sanitize(params.user_id)
        safe_last_date = params.last_date[:10] if params.last_date else ""

        path = template.format(
            service=safe_service,
            name=safe_name,
            alias=safe_alias or safe_name,
            user_id=safe_user_id,
            last_date=safe_last_date
        )
        return Path(path)

    # ==================== Level 2: Post Folder ====================

    @staticmethod
    def format_post_folder(params: PostFolderParams, template: str, date_format: str) -> Path:
        """Format post folder path"""
        published_str = Formatter._format_date(params.published, date_format)
        safe_id = Formatter._sanitize(params.id)
        safe_user = Formatter._sanitize(params.user)
        safe_service = Formatter._sanitize(params.service)
        # safe_title = Formatter._sanitize(params.title[:50])
        safe_title = Formatter._sanitize(params.title)

        path = template.format(
            id=safe_id,
            user=safe_user,
            service=safe_service,
            title=safe_title,
            published=published_str
        )
        return Path(path)

    # ==================== Level 3: File Name ====================

    @staticmethod
    def format_file_name(params: FileParams, template: str) -> str:
        """Format single file name"""
        safe_name = Formatter._sanitize(params.name)
        name = template.format(
            idx=params.idx,
            index=f"{params.idx:03d}",
            name=safe_name,
            filename=safe_name
        )
        # Add extension if missing
        if '.' not in name and '.' in params.name:
            ext = params.name.rsplit('.', 1)[-1]
            name = f"{name}.{ext}"

        return name

    @staticmethod
    def format_files_names(file_names: List[str], template: str,
                          rename_images_only: bool, image_extensions: set) -> List[str]:
        """Format multiple file names with rename_images_only logic"""
        formatted_names = []
        image_index = 0

        for i, original_name in enumerate(file_names):
            ext = Path(original_name).suffix.lower()
            is_image = ext in image_extensions
            should_rename = not rename_images_only or is_image

            if should_rename:
                idx = image_index if (rename_images_only and is_image) else i
                if is_image:
                    image_index += 1

                file_params = FileParams(name=original_name, idx=idx)
                formatted_name = Formatter.format_file_name(file_params, template)
            else:
                formatted_name = Formatter._sanitize(original_name)

            formatted_names.append(formatted_name)

        return formatted_names

    # ==================== Private ====================

    @staticmethod
    def _sanitize(text: str) -> str:
        """Sanitize path component"""
        if not text:
            return "unknown"

        result = text

        # Remove ASCII control characters (0x00-0x1F, 0x7F)
        result = re.sub(r'[\x00-\x1F\x7F]', '', result)

        # Character replacement map
        char_map = {
            # Remove zero-width characters (invisible but affect paths)
            '\u200b': '',  # Zero-width space
            '\u200c': '',  # Zero-width non-joiner
            '\u200d': '',  # Zero-width joiner
            '\ufeff': '',  # Zero-width no-break space / BOM
            # Remove direction marks (affect text display)
            '\u200e': '',  # Left-to-right mark
            '\u200f': '',  # Right-to-left mark
            # Normalize Unicode spaces to normal space
            '\u3000': ' ',  # Full-width space
            '\u00a0': ' ',  # Non-breaking space
            '\u2003': ' ',  # Em space
            '\u2002': ' ',  # En space
            '\t': ' ',      # Tab
            '\r': ' ',      # Carriage return
            '\n': ' ',      # Line feed
            # Full-width punctuation to half-width (commented out - optional)
            # '！': '!',
            # '（': '(',
            # '）': ')',
            # '，': ',',
            # '。': '.',
            # '：': ':',
            # '；': ';',
            # Full-width digits to half-width (commented out - optional)
            # '０': '0',
            # '１': '1',
            # '２': '2',
            # '３': '3',
            # '４': '4',
            # '５': '5',
            # '６': '6',
            # '７': '7',
            # '８': '8',
            # '９': '9',
            # Replace Windows forbidden characters with full-width equivalents
            '/': '／',
            '\\': '＼',
            ':': '：',
            '*': '＊',
            '?': '？',
            '"': '＂',
            '<': '＜',
            '>': '＞',
            '|': '｜',
        }

        for char, replacement in char_map.items():
            result = result.replace(char, replacement)

        # Compress consecutive spaces
        result = re.sub(r' +', ' ', result)

        result = result.strip(' .')
        return result or "unknown"

    @staticmethod
    def _format_date(date_str: str, date_format: str) -> str:
        """Format ISO date string"""
        if not date_str:
            return ""
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime(date_format)
        except:
            return date_str[:10]
