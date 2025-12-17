from urllib.parse import urlparse, unquote
from src.models import FileParams, PostFolderParams, ArtistFolderParams


def format_artist_plugin(func):
    """Decorator: preprocess artist params before formatter runs.

    Logic: For service 'example', uppercase the artist name.
    """
    def wrapper(params: ArtistFolderParams, template: str):
        return func(params, template)
    return wrapper


def format_post_plugin(func):
    """Decorator: preprocess post title before formatter runs.

    Logic: For patreon user 99342295, truncate title at first '/'.
    """
    def wrapper(params: PostFolderParams, template: str, date_format: str):
        if params.service == "patreon" and params.user == "99342295" and "/" in params.title:
            params = PostFolderParams(params.id, params.user, params.service, params.title.split("/", 1)[0].strip(), params.published)
        return func(params, template, date_format)
    return wrapper


def format_file_plugin(func):
    """Decorator: preprocess file params before formatter runs.

    Logic: truncate original name to 20 chars (keep idx).
    """
    def wrapper(params: FileParams, template: str):

        # when the params.name is a URL, extract the filename from the URL
        if params.name.startswith("http://") or params.name.startswith("https://"):
            parsed_url = urlparse(params.name)
            filename = unquote(parsed_url.path.split("/")[-1])[-20:] # get last 20 chars of filename

            if '.' not in filename:
                if params.name.startswith("https://www.patreon.com/media-u/"):
                    filename = filename + ".jpg"
                else:
                    filename = filename + ".bin"

            params = FileParams(params.idx, filename)

        return func(params, template)
    return wrapper
