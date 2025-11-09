from typing import Dict, List

from .models import Post


class PostFilter:
    """Post filtering system with built-in filter functions"""

    # ==================== Built-in Filter Functions ====================

    @staticmethod
    def contains_keyword(post: Post, keyword: str) -> bool:
        """Check if post title or content contains keyword"""
        text = f"{post.title} {post.content}".lower()
        return keyword.lower() in text

    @staticmethod
    def not_contains_keyword(post: Post, keyword: str) -> bool:
        """Check if post title or content does not contain keyword"""
        return not PostFilter.contains_keyword(post, keyword)

    @staticmethod
    def contains_any_keywords(post: Post, keywords: List[str]) -> bool:
        """Check if post contains any of the keywords"""
        return any(PostFilter.contains_keyword(post, kw) for kw in keywords)

    @staticmethod
    def contains_all_keywords(post: Post, keywords: List[str]) -> bool:
        """Check if post contains all keywords"""
        return all(PostFilter.contains_keyword(post, kw) for kw in keywords)

    @staticmethod
    def has_attachments(post: Post) -> bool:
        """Check if post has attachments"""
        return bool(post.attachments)

    @staticmethod
    def has_file(post: Post) -> bool:
        """Check if post has main file"""
        return bool(post.file)

    @staticmethod
    def has_any_files(post: Post) -> bool:
        """Check if post has any files"""
        return bool(post.file or post.attachments)

    @staticmethod
    def published_after(post: Post, date_str: str) -> bool:
        """Check if post was published after specified date (YYYY-MM-DD)"""
        try:
            post_date = post.published.split('T')[0] if post.published else ""
            return post_date > date_str
        except:
            return False

    @staticmethod
    def published_before(post: Post, date_str: str) -> bool:
        """Check if post was published before specified date (YYYY-MM-DD)"""
        try:
            post_date = post.published.split('T')[0] if post.published else ""
            return post_date < date_str
        except:
            return False

    @staticmethod
    def published_between(post: Post, start_date: str, end_date: str) -> bool:
        """Check if post was published between dates (YYYY-MM-DD)"""
        return (PostFilter.published_after(post, start_date) and
                PostFilter.published_before(post, end_date))

    # ==================== Filter Application ====================

    @staticmethod
    def apply_filters(posts: List[Post], filter_config: Dict) -> List[Post]:
        """
        Apply filters to posts based on filter configuration

        Filter config format:
        {
            "include_keywords": ["keyword1", "keyword2"],  # Must contain any
            "exclude_keywords": ["keyword3", "keyword4"],  # Must not contain any
            "require_all_keywords": ["keyword5", "keyword6"],  # Must contain all
            "require_files": true,  # Must have files
            "require_attachments": true,  # Must have attachments
            "published_after": "2024-01-01",  # Published after date
            "published_before": "2025-01-01",  # Published before date
        }
        """
        if not filter_config:
            return posts

        filtered_posts = []

        for post in posts:
            # Check include keywords (OR logic)
            if "include_keywords" in filter_config:
                keywords = filter_config["include_keywords"]
                if keywords and not PostFilter.contains_any_keywords(post, keywords):
                    continue

            # Check exclude keywords (OR logic)
            if "exclude_keywords" in filter_config:
                keywords = filter_config["exclude_keywords"]
                if keywords and PostFilter.contains_any_keywords(post, keywords):
                    continue

            # Check require all keywords (AND logic)
            if "require_all_keywords" in filter_config:
                keywords = filter_config["require_all_keywords"]
                if keywords and not PostFilter.contains_all_keywords(post, keywords):
                    continue

            # Check require files
            if filter_config.get("require_files"):
                if not PostFilter.has_any_files(post):
                    continue

            # Check require attachments
            if filter_config.get("require_attachments"):
                if not PostFilter.has_attachments(post):
                    continue

            # Check published after
            if "published_after" in filter_config:
                date_str = filter_config["published_after"]
                if date_str and not PostFilter.published_after(post, date_str):
                    continue

            # Check published before
            if "published_before" in filter_config:
                date_str = filter_config["published_before"]
                if date_str and not PostFilter.published_before(post, date_str):
                    continue

            # Post passed all filters
            filtered_posts.append(post)

        return filtered_posts
