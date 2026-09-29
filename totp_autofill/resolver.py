"""Decide qué cuenta usar según el contexto, sin necesidad de configurar URLs.

El contexto sale de la accesibilidad (host de la página, texto visible,
usuario escrito) o, si no hay, del título de la ventana activa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .store import Account, clean_title


@dataclass
class Context:
    host: str = ""  # host[:puerto] de la página (solo con accesibilidad)
    title: str = ""  # título de la ventana activa
    page_text: str = ""  # texto visible de la página, para buscar emails
    recent_user: str = ""  # usuario escrito hace poco en ese sitio


@dataclass
class Resolution:
    account: Account | None  # elegida sin preguntar, o None
    via: str = ""  # "site", "title" u "only": cómo se eligió
    candidates: list[Account] = field(default_factory=list)  # para el selector

    @property
    def trusted(self) -> bool:
        """Solo el host lo fija el navegador; el título lo controla la página.

        El modo automático solo escribe si la cuenta se eligió por el sitio.
        """
        return self.account is not None and self.via == "site"


def _by_user(accounts: list[Account], ctx: Context) -> list[Account]:
    """Filtra por el usuario escrito o, si no, por el que aparece en la página."""
    if ctx.recent_user:
        same = [a for a in accounts if a.username and
                a.username.lower() == ctx.recent_user.strip().lower()]
        if len(same) == 1:
            return same
    text = ctx.page_text.lower()
    if text:
        shown = [a for a in accounts if a.username and a.username.lower() in text]
        if len(shown) == 1:
            return shown
    return accounts


def resolve(accounts: list[Account], ctx: Context) -> Resolution:
    by_site = [a for a in accounts if ctx.host and a.matches_host(ctx.host)]
    title = clean_title(ctx.title)
    by_title = [a for a in accounts if title and title in a.window_titles]

    for matched, via in ((by_site, "site"), (by_title, "title")):
        if not matched:
            continue
        narrowed = _by_user(matched, ctx)
        rest = [a for a in accounts if a not in matched]
        others = [a for a in matched if a not in narrowed]
        candidates = [*narrowed, *others, *rest]
        if len(narrowed) == 1:
            return Resolution(narrowed[0], via, candidates)
        return Resolution(None, "", candidates)

    if len(accounts) == 1:
        return Resolution(accounts[0], "only", list(accounts))
    # Sin asociación: se pregunta, con las cuentas más probables primero.
    likely = _by_user(accounts, ctx)
    return Resolution(None, "", likely + [a for a in accounts if a not in likely])
