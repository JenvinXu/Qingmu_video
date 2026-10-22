"""Explicit provider limits, kept separate from the app's 30/3/3 workspace limits."""


def video_capabilities(model):
    if model == "agnes-video-2.5-flash":
        return {
            "images": 5,
            "audios": 3,
            "videos": 0,
            # Real image + audio generation verified with local Data URI inputs.
            "public_urls": False,
            "sizes": ["720P"],
        }
    if model == "agnes-video-2.5":
        return {
            "images": 8,
            "audios": 3,
            "videos": 1,
            "public_urls": True,
            "sizes": ["720P", "1080P", "1K", "2K"],
        }
    return {
        "images": 30,
        "audios": 3,
        "videos": 3,
        "public_urls": True,
        "sizes": ["720P", "1080P", "1K", "2K"],
    }
