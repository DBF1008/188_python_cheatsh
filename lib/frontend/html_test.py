from frontend.html import _restore_sheet_path


def test_root_page_path_is_unchanged():
    # Top-level cheat sheets live directly under `sheets/` with no directory,
    # so no underscore should be added.
    assert _restore_sheet_path("btrfs") == "btrfs"
    assert _restore_sheet_path("g++") == "g++"


def test_single_directory_path_is_restored():
    # The single directory component gets its hidden leading underscore back.
    assert _restore_sheet_path("python/lambda") == "_python/lambda"


def test_nested_directory_path_is_restored():
    # Every directory component must be restored, not just the first one.
    assert _restore_sheet_path("python/django/templates") == "_python/_django/templates"
    assert _restore_sheet_path("a/b/c/d") == "_a/_b/_c/d"
