"""
Início automático do app no logon do usuário (Windows).

Usa a chave de registro por usuário
    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
que NÃO exige privilégios de administrador. Ativar grava ali um valor
apontando para o pythonw.exe + o script; desativar remove esse valor.

O NOME do valor é único por PASTA da aplicação (derivado do caminho), de forma
que cópias diferentes do app (ex.: desenvolvimento e produção) tenham cada uma
a sua própria entrada e não se sobrescrevam. Assim, ativar/desativar numa cópia
nunca mexe na entrada da outra.

Fora do Windows (ou se o módulo `winreg` não existir) as funções viram
operações inofensivas: `esta_ativo` devolve False e `definir` devolve False.
"""

from __future__ import annotations

import hashlib
import os
import sys

try:
    import winreg  # só existe no Windows
except ImportError:  # pragma: no cover - ambientes não-Windows
    winreg = None  # type: ignore

_CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_PASTA = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_PASTA, "foco_pomodoro.py")

# Nome do valor gravado na chave Run: único por pasta. O sufixo curto vem do
# hash do caminho, garantindo que dev e prod fiquem separados mesmo que as
# pastas tenham o mesmo nome. É também o nome exibido na aba "Inicializar" do
# Gerenciador de Tarefas.
_ID = hashlib.md5(_PASTA.lower().encode("utf-8")).hexdigest()[:4]
_NOME_VALOR = f"Foco Pomodoro ({os.path.basename(_PASTA)} - {_ID})"

# Nome fixo usado por versões anteriores do app (mesmo valor para todas as
# cópias). Mantido só para migração automática -> _NOME_VALOR.
_NOME_LEGADO = "FocoPomodoro"

# Pasta desta cópia, exposta para a UI mostrar "qual instalação é esta".
PASTA = _PASTA


def _comando_inicializacao() -> str:
    """Linha de comando que o Windows executará no logon (sem janela de
    console, via pythonw.exe quando disponível)."""
    pasta_py = os.path.dirname(sys.executable)
    pythonw = os.path.join(pasta_py, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fallback (pode abrir um console)
    return f'"{pythonw}" "{_SCRIPT}"'


def _aponta_para_esta_copia(valor) -> bool:
    """True se o comando gravado no registro se refere ao script desta pasta."""
    return _SCRIPT.lower() in str(valor).lower()


def disponivel() -> bool:
    """True se dá para mexer no início automático (ou seja, no Windows)."""
    return winreg is not None


def migrar_legado() -> None:
    """Converte a entrada antiga (nome fixo, compartilhado entre cópias) para o
    novo valor único por pasta — mas só se ela pertencer a ESTA cópia. Se o
    valor legado apontar para outra pasta, não mexe (é de outra instalação)."""
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN) as chave:
            try:
                legado, _ = winreg.QueryValueEx(chave, _NOME_LEGADO)
            except FileNotFoundError:
                return  # nada a migrar
        if not _aponta_para_esta_copia(legado):
            return  # entrada legada é de outra cópia; não tocar
        # Recria como valor por pasta e remove o legado.
        definir(True)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _CHAVE_RUN, 0, winreg.KEY_SET_VALUE,
        ) as chave:
            try:
                winreg.DeleteValue(chave, _NOME_LEGADO)
            except FileNotFoundError:
                pass
    except OSError:
        pass


def esta_ativo() -> bool:
    """True se o app já está registrado para iniciar no logon."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN) as chave:
            valor, _ = winreg.QueryValueEx(chave, _NOME_VALOR)
        return bool(valor)
    except OSError:
        return False


def definir(ativo: bool) -> bool:
    """Ativa ou desativa o início automático no logon.

    Retorna True se a operação foi aplicada com sucesso; False se não foi
    possível (fora do Windows ou erro de acesso ao registro)."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _CHAVE_RUN, 0, winreg.KEY_SET_VALUE,
        ) as chave:
            if ativo:
                winreg.SetValueEx(
                    chave, _NOME_VALOR, 0, winreg.REG_SZ,
                    _comando_inicializacao(),
                )
            else:
                try:
                    winreg.DeleteValue(chave, _NOME_VALOR)
                except FileNotFoundError:
                    pass  # já não estava registrado
        return True
    except OSError:
        return False
