"""
Cria o ícone do app (foco.ico) e um atalho bonito do Windows
(_FocoPomodo_INICIAR.lnk) que abre a aplicação sem janela de console.

Execute uma vez:
    python criar_atalho.py

Tudo usa apenas a biblioteca padrão. O ícone é um tomate desenhado por
código, nas cores do tema, e gravado como .ico (PNG embutido).
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import zlib

PASTA = os.path.dirname(os.path.abspath(__file__))
ICONE = os.path.join(PASTA, "foco.ico")
# Variantes usadas na barra de tarefas conforme o estado do timer.
ICONE_INTERVALO = os.path.join(PASTA, "foco_intervalo.ico")
ICONE_OCIOSO = os.path.join(PASTA, "foco_ocioso.ico")
ATALHO = os.path.join(PASTA, "_FocoPomodo_INICIAR.lnk")
SCRIPT = os.path.join(PASTA, "foco_pomodoro.py")

# Cores dos corpos do tomate (RGB), casando com o tema do app.
COR_TOMATE_FOCO = (255, 107, 107)      # vermelho-tomate (foco)
COR_TOMATE_INTERVALO = (78, 201, 166)  # verde-menta (intervalo)

S = 256  # tamanho do ícone (256x256)


# --------------------------------------------------------------------------- #
# Helpers de desenho (com anti-aliasing simples por cobertura)
# --------------------------------------------------------------------------- #
def _clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def _over(buf, i, r, g, b, a):
    """Compõe a cor (r,g,b) com cobertura a sobre o pixel existente."""
    if a <= 0:
        return
    buf[i]     = int(r * a + buf[i]     * (1 - a))
    buf[i + 1] = int(g * a + buf[i + 1] * (1 - a))
    buf[i + 2] = int(b * a + buf[i + 2] * (1 - a))
    buf[i + 3] = int(255 * a + buf[i + 3] * (1 - a))


def _cob_elipse(x, y, cx, cy, rx, ry):
    """Cobertura (0..1) de um ponto dentro de uma elipse, com borda suave."""
    val = math.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
    aa = 1.5 / ((rx + ry) / 2)
    return _clamp((1.0 - val) / aa)


def _cob_elipse_rot(x, y, cx, cy, hl, hw, ang):
    """Cobertura de elipse orientada (para as folhas)."""
    dx, dy = x - cx, y - cy
    c, s = math.cos(-ang), math.sin(-ang)
    u = dx * c - dy * s
    v = dx * s + dy * c
    val = math.sqrt((u / hl) ** 2 + (v / hw) ** 2)
    aa = 1.5 / ((hl + hw) / 2)
    return _clamp((1.0 - val) / aa)


def _cob_retangulo_arredondado(x, y, cx, cy, halfw, halfh, r):
    qx = max(abs(x - cx) - (halfw - r), 0.0)
    qy = max(abs(y - cy) - (halfh - r), 0.0)
    d = math.sqrt(qx * qx + qy * qy) - r
    return _clamp(0.5 - d)


# --------------------------------------------------------------------------- #
# Desenho do tomate
# --------------------------------------------------------------------------- #
def _desenhar(cor_corpo=COR_TOMATE_FOCO) -> bytearray:
    buf = bytearray(S * S * 4)  # RGBA, começa transparente
    cr, cg, cb = cor_corpo

    # Centro do tomate e do brilho.
    cx, cy, rx, ry = 128, 152, 92, 84
    hx, hy = 98, 120  # ponto de luz

    # Coroa de folhas (calyx) no topo.
    lx, ly = 128, 96
    angulos = [math.radians(a) for a in (270, 215, 325, 175, 5)]

    for y in range(S):
        for x in range(S):
            i = (y * S + x) * 4

            # 1) Fundo: quadrado arredondado com leve gradiente.
            cob_bg = _cob_retangulo_arredondado(x, y, 128, 128, 120, 120, 44)
            if cob_bg > 0:
                t = y / S
                br = int(40 + (30 - 40) * t)
                bg = int(43 + (32 - 43) * t)
                bb = int(61 + (48 - 61) * t)
                _over(buf, i, br, bg, bb, cob_bg)

            # 2) Folhas verdes (atrás do corpo, aparecem no topo).
            cob_folha = 0.0
            for ang in angulos:
                fx = lx + 30 * math.cos(ang)
                fy = ly + 30 * math.sin(ang)
                cob_folha = max(cob_folha, _cob_elipse_rot(x, y, fx, fy, 34, 13, ang))
            if cob_folha > 0:
                _over(buf, i, 78, 201, 166, cob_folha)

            # 3) Corpo do tomate (por cima da base das folhas).
            cob_t = _cob_elipse(x, y, cx, cy, rx, ry)
            if cob_t > 0:
                # Sombreamento: brilho perto de (hx,hy), escuro embaixo.
                dist_luz = math.hypot(x - hx, y - hy)
                luz = _clamp(1 - dist_luz / 130) * 0.55
                sombra = _clamp((y - cy) / ry) * 0.28
                fator = 1 + luz - sombra
                r = int(_clamp(cr * fator, 0, 255))
                g = int(_clamp(cg * fator, 0, 255))
                b = int(_clamp(cb * fator, 0, 255))
                _over(buf, i, r, g, b, cob_t)

            # 4) Caule curto no topo.
            cob_caule = _cob_retangulo_arredondado(x, y, 128, 80, 7, 16, 5)
            if cob_caule > 0:
                _over(buf, i, 64, 150, 120, cob_caule)

    return buf


def _acinzentar(buf: bytearray) -> bytearray:
    """Converte o desenho para tons de cinza esmaecidos (estado ocioso)."""
    for i in range(0, len(buf), 4):
        a = buf[i + 3]
        if a == 0:
            continue
        # Luminância perceptual, puxada para um cinza claro e discreto.
        lum = int(0.299 * buf[i] + 0.587 * buf[i + 1] + 0.114 * buf[i + 2])
        cinza = int(_clamp(90 + lum * 0.45, 0, 255))
        buf[i] = buf[i + 1] = buf[i + 2] = cinza
    return buf


# --------------------------------------------------------------------------- #
# Codificação PNG + ICO (apenas stdlib)
# --------------------------------------------------------------------------- #
def _png_bytes(w: int, h: int, rgba: bytearray) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    assinatura = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # RGBA 8 bits
    bruto = bytearray()
    for y in range(h):
        bruto.append(0)  # filtro 'none' por linha
        bruto += rgba[y * w * 4:(y + 1) * w * 4]
    idat = zlib.compress(bytes(bruto), 9)
    return assinatura + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _gravar_ico(caminho: str, buf: bytearray) -> None:
    png = _png_bytes(S, S, buf)
    cabecalho = struct.pack("<HHH", 0, 1, 1)  # reservado, tipo=ícone, 1 imagem
    entrada = struct.pack(
        "<BBBBHHII",
        0, 0,        # largura/altura 0 => 256
        0, 0,        # cores na paleta / reservado
        1, 32,       # planos, bits por pixel
        len(png), 6 + 16,  # tamanho e offset dos dados
    )
    with open(caminho, "wb") as f:
        f.write(cabecalho + entrada + png)


def gerar_icone() -> None:
    """Gera o ícone padrão (tomate vermelho) e as variantes de estado
    usadas na barra de tarefas: intervalo (verde) e ocioso (cinza)."""
    _gravar_ico(ICONE, _desenhar(COR_TOMATE_FOCO))
    print(f"Ícone gerado: {ICONE}")
    _gravar_ico(ICONE_INTERVALO, _desenhar(COR_TOMATE_INTERVALO))
    print(f"Ícone gerado: {ICONE_INTERVALO}")
    _gravar_ico(ICONE_OCIOSO, _acinzentar(_desenhar(COR_TOMATE_FOCO)))
    print(f"Ícone gerado: {ICONE_OCIOSO}")


# --------------------------------------------------------------------------- #
# Criação do atalho .lnk
# --------------------------------------------------------------------------- #
def criar_atalho() -> None:
    pasta_py = os.path.dirname(sys.executable)
    pythonw = os.path.join(pasta_py, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fallback (abrirá com console)

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{ATALHO}')
$sc.TargetPath = '{pythonw}'
$sc.Arguments = '"{SCRIPT}"'
$sc.WorkingDirectory = '{PASTA}'
$sc.IconLocation = '{ICONE}'
$sc.Description = 'Foco Pomodoro - timer de foco'
$sc.WindowStyle = 1
$sc.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True,
    )
    print(f"Atalho criado: {ATALHO}")


if __name__ == "__main__":
    gerar_icone()
    criar_atalho()
    print("Pronto! Use o atalho _FocoPomodo_INICIAR para abrir o app.")
