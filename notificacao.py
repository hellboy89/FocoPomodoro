"""
Notificações nativas (toast) do Windows 10/11.

Usa o PowerShell e as APIs Windows.UI.Notifications, sem precisar instalar
nenhum módulo. A notificação é disparada em segundo plano (sem abrir janela
do PowerShell) e não trava a aplicação.
"""

from __future__ import annotations

import subprocess
import sys

# AppID já registrado no Windows (o do próprio PowerShell). Garante que a
# notificação apareça de forma confiável no Win10/11.
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_CREATE_NO_WINDOW = 0x08000000


def _escapar_xml(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def notificar(titulo: str, mensagem: str) -> None:
    """Dispara uma notificação toast (silenciosa quanto a janelas)."""
    if not sys.platform.startswith("win"):
        return

    titulo = _escapar_xml(titulo)
    mensagem = _escapar_xml(mensagem)

    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@"
<toast scenario='reminder'>
  <visual>
    <binding template='ToastGeneric'>
      <text>{titulo}</text>
      <text>{mensagem}</text>
    </binding>
  </visual>
</toast>
"@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($toast)
"""

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # Se algo falhar (PowerShell ausente, política, etc.), apenas ignora.
        pass
