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
        # result = func(params, template)
        # ext = '.' + result.rsplit('.', 1)[-1] if '.' in result else ''
        # name_only = result.rsplit('.', 1)[0] if '.' in result else result
        # if len(name_only) > 20:
        #     name_only = name_only[:10]
        # if len(ext) > 10:
        #     ext = ext[:10]
        # return name_only + ext
        return func(params, template)
    return wrapper
