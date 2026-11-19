import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GameDefinition:
    identifier: str
    name: str
    mod_directory: str


BF2_GAME = GameDefinition("bf2", "Battlefield 2", "bf2")
BF2142_GAME = GameDefinition("bf2142", "Battlefield 2142", "bf2142")
SUPPORTED_GAMES = (BF2_GAME, BF2142_GAME)


def normalize_directory(directory):
    if not directory:
        return ""
    return os.path.normpath(
        os.path.abspath(os.path.expanduser(os.fspath(directory)))
    )


def get_game_mod_directory(install_directory, game):
    install_directory = normalize_directory(install_directory)
    if not install_directory:
        return ""
    return os.path.join(install_directory, "mods", game.mod_directory)


def get_game_install_error(install_directory, game):
    install_directory = normalize_directory(install_directory)
    if not install_directory:
        return ""
    if not os.path.isdir(install_directory):
        return f"{game.name} install folder does not exist"
    mod_directory = get_game_mod_directory(install_directory, game)
    if not os.path.isdir(mod_directory):
        return (
            f"Expected asset directory is missing: "
            f"{os.path.join('mods', game.mod_directory)}"
        )
    return ""


def prioritize_mod_directories(mod_directories, source_path):
    mod_directories = list(mod_directories)
    if not source_path:
        return mod_directories

    source_path = normalize_directory(source_path)
    source_key = os.path.normcase(source_path)
    matches = []
    remaining = []
    for index, mod_directory in enumerate(mod_directories):
        mod_key = os.path.normcase(normalize_directory(mod_directory))
        try:
            is_match = os.path.commonpath((source_key, mod_key)) == mod_key
        except ValueError:
            is_match = False
        if is_match:
            matches.append((len(mod_key), index, mod_directory))
        else:
            remaining.append(mod_directory)

    matches.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in matches] + remaining


def collect_mod_directories(
    game_install_directories,
    additional_mod_directories=(),
    source_path="",
):
    candidates = []
    for game in SUPPORTED_GAMES:
        install_directory = game_install_directories.get(game.identifier, "")
        candidates.append(get_game_mod_directory(install_directory, game))
    candidates.extend(additional_mod_directories)

    mod_directories = []
    seen = set()
    for candidate in candidates:
        directory = normalize_directory(candidate)
        key = os.path.normcase(directory)
        if not directory or key in seen or not os.path.isdir(directory):
            continue
        seen.add(key)
        mod_directories.append(directory)

    return prioritize_mod_directories(mod_directories, source_path)
