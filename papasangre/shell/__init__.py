"""The bits around the game: menus, and the options they set."""

from .menu import (CREDITS, Menu, MenuItem, level_complete_menu,
                   level_failed_menu, keys_menu, level_menu,
                   main_menu, options_menu, pad_menu, pause_menu)

__all__ = ['CREDITS', 'Menu', 'MenuItem', 'level_complete_menu',
           'keys_menu', 'level_failed_menu', 'level_menu', 'main_menu',
           'options_menu', 'pad_menu', 'pause_menu']
