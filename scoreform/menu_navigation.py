"""ScoreForm adapters for the shared PDS menu navigation primitives."""

from pds_core.menu_navigation import (
    NavigationChoice,
    navigation_hint,
    parse_navigation_choice,
    print_navigation_options,
)


def print_scoreform_navigation_options(
    *, back: bool = True, main_menu: bool = True, quit: bool = True
) -> None:
    """Render shared navigation options for a ScoreForm controlled menu."""
    print_navigation_options(back=back, main_menu=main_menu, quit=quit)


def parse_scoreform_navigation(
    value: str,
    *,
    allow_back: bool = True,
    allow_main_menu: bool = True,
    allow_quit: bool = True,
) -> NavigationChoice | None:
    """Delegate controlled-menu navigation parsing to pds-core."""
    return parse_navigation_choice(
        value,
        allow_back=allow_back,
        allow_main_menu=allow_main_menu,
        allow_quit=allow_quit,
    )


def print_invalid_navigation() -> None:
    """Print the shared invalid-selection hint."""
    print(navigation_hint())
