"""
Ícone na bandeja do sistema (área de notificação, ao lado do relógio) que
muda automaticamente conforme o estado do timer:

  * focando   -> tomate vermelho (foco.ico)
  * intervalo -> tomate verde    (foco_intervalo.ico)
  * parado    -> tomate cinza    (foco_ocioso.ico)

Usa `pystray` + `Pillow`. Se essas bibliotecas não estiverem instaladas, o
próprio app tenta instalá-las automaticamente (no escopo do usuário, sem
exigir administrador). Se a instalação ou a criação do ícone falhar por
qualquer motivo, o aplicativo continua funcionando normalmente — apenas sem
o ícone na bandeja.

Toda a inicialização (incluindo a possível instalação via pip) roda numa
thread separada, para não travar a abertura da janela.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

_PASTA = os.path.dirname(os.path.abspath(__file__))
_CREATE_NO_WINDOW = 0x08000000  # evita piscar janela de console (pythonw)

# Estado -> arquivo de ícone correspondente.
_ARQUIVOS = {
    "foco": "foco.ico",
    "intervalo": "foco_intervalo.ico",
    "ocioso": "foco_ocioso.ico",
}

# Primeira linha do texto (tooltip) mostrado ao passar o mouse sobre o ícone.
# A segunda linha, opcional, é o tempo restante enviado pelo app a cada tique.
_TOOLTIPS = {
    "foco": "Foco Pomodoro — focando 🍅",
    "intervalo": "Foco Pomodoro — intervalo ☕",
    "ocioso": "Foco Pomodoro — parado",
}

# O tooltip da bandeja do Windows (szTip) trunca em 128 caracteres.
_LIMITE_TOOLTIP = 127


def _garantir_libs() -> bool:
    """Garante pystray + Pillow importáveis, instalando-as se preciso.

    Retorna True se, ao final, ambas puderem ser importadas."""
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        pass

    # Tenta instalar no escopo do usuário (não requer admin). Se o Python
    # estiver numa pasta gravável, o --user é inofensivo mesmo assim.
    for args in (
        [sys.executable, "-m", "pip", "install", "--user", "--quiet",
         "--disable-pip-version-check", "pystray", "Pillow"],
        [sys.executable, "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "pystray", "Pillow"],
    ):
        try:
            subprocess.run(
                args,
                check=True,
                creationflags=_CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue
        # O diretório recém-criado de site-packages do usuário pode não estar
        # no sys.path desta sessão; garante que passe a estar.
        try:
            import site
            import importlib
            importlib.reload(site)
        except Exception:
            pass
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except ImportError:
            continue
    return False


class Bandeja:
    """Gerencia o ícone da bandeja e sua troca conforme o estado do app."""

    def __init__(self, app) -> None:
        self.app = app
        self.icon = None
        self._imagens: dict[str, object] = {}
        self._estado = "ocioso"   # estado desejado atual
        self._detalhe = ""        # 2ª linha do tooltip (ex.: "23:45 restantes")
        self._titulo_aplicado = None  # último tooltip realmente enviado ao SO
        self.disponivel = False
        self._lock = threading.Lock()

    @staticmethod
    def _montar_titulo(estado: str, detalhe: str) -> str:
        """Monta o tooltip: estado na 1ª linha, tempo restante na 2ª."""
        titulo = _TOOLTIPS[estado]
        if detalhe:
            titulo = f"{titulo}\n{detalhe}"
        return titulo[:_LIMITE_TOOLTIP]

    # ------------------------------------------------------------------ #
    def iniciar(self) -> None:
        """Sobe o ícone da bandeja em segundo plano (não bloqueia a UI)."""
        threading.Thread(target=self._iniciar_bg, daemon=True).start()

    def _iniciar_bg(self) -> None:
        if not _garantir_libs():
            return  # segue sem bandeja
        try:
            import pystray
            self._carregar_imagens()
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Abrir Foco Pomodoro", self._abrir, default=True,
                ),
                pystray.MenuItem("Sair", self._sair),
            )
            with self._lock:
                chave = self._estado
                titulo = self._montar_titulo(chave, self._detalhe)
            self.icon = pystray.Icon(
                "foco_pomodoro",
                self._imagens[chave],
                titulo,
                menu,
            )
            self._titulo_aplicado = titulo
            self.disponivel = True
            # run() bloqueia esta thread (daemon) até icon.stop().
            self.icon.run()
        except Exception:
            self.disponivel = False

    def _carregar_imagens(self) -> None:
        from PIL import Image

        faltando = [
            nome for nome in _ARQUIVOS.values()
            if not os.path.exists(os.path.join(_PASTA, nome))
        ]
        if faltando:
            # Gera os .ico que faltarem (mesma rotina do atalho, só stdlib).
            try:
                import criar_atalho
                criar_atalho.gerar_icone()
            except Exception:
                pass

        for chave, nome in _ARQUIVOS.items():
            caminho = os.path.join(_PASTA, nome)
            self._imagens[chave] = Image.open(caminho).convert("RGBA")

    # ------------------------------------------------------------------ #
    def atualizar(self, estado: str, detalhe: str = "") -> None:
        """Troca o ícone da bandeja para o estado indicado
        ('foco', 'intervalo' ou 'ocioso') e ajusta o tooltip.

        `detalhe` vira a 2ª linha do tooltip — o app manda o tempo restante a
        cada segundo, para que passar o mouse sobre o ícone mostre a contagem.
        Seguro chamar a qualquer momento, mesmo antes de o ícone estar pronto."""
        if estado not in _ARQUIVOS:
            return
        with self._lock:
            self._estado = estado
            self._detalhe = detalhe
            titulo = self._montar_titulo(estado, detalhe)
        if not self.disponivel or self.icon is None:
            return  # ainda inicializando; será aplicado ao ficar pronto
        img = self._imagens.get(estado)
        if img is None:
            return
        # Chamado a cada segundo: só fala com o SO quando algo mudou de fato.
        if titulo == self._titulo_aplicado and self.icon.icon is img:
            return
        try:
            self.icon.icon = img
            self.icon.title = titulo
            self._titulo_aplicado = titulo
        except Exception:
            pass

    def parar(self) -> None:
        """Remove o ícone da bandeja (ao fechar o app)."""
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.disponivel = False

    # ------------------------------------------------------------------ #
    # Ações do menu (rodam na thread do pystray -> devolvem para a do tk).
    # ------------------------------------------------------------------ #
    def _abrir(self, icon=None, item=None) -> None:
        try:
            self.app.root.after(0, self.app._restaurar_da_bandeja)
        except Exception:
            pass

    def _sair(self, icon=None, item=None) -> None:
        try:
            self.app.root.after(0, self.app._sair_pela_bandeja)
        except Exception:
            pass
