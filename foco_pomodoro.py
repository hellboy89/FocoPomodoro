"""
Foco Pomodoro — um timer Pomodoro visual para estudos e trabalho.

Recursos:
  * Tempos de foco e de intervalo configuráveis.
  * Opção de desligar os intervalos (um pomodoro após o outro) e de
    desligar o início automático do próximo ciclo.
  * Campo de descrição preenchido antes de iniciar (estudos, trabalho...).
  * Histórico persistente em JSON com tempo total de foco e exportação CSV.
  * Edição/remoção de registros individuais na aba Histórico (duplo clique,
    botão direito ou botões Editar/Remover), com estatísticas recalculadas.
  * Inclusão manual de registros no histórico (botão Adicionar), para
    contabilizar focos feitos longe do computador.
  * Foco interrompido no meio é aproveitado como registro parcial (◐).
  * Aba Estatísticas: gráfico dos últimos 14 dias, sequência de dias
    (streak), meta diária de pomodoros e média por dia.
  * Aba Jardim: cada pomodoro concluído "planta" uma muda no canteiro do
    dia; as plantas amadurecem conforme a sequência (broto → flor → árvore)
    e a floresta resume os últimos 7 dias. Tudo derivado do histórico.
  * Prorrogação do foco ao fim de um pomodoro (minutos configuráveis).
  * Som ambiente opcional durante o foco (tique-taque ou chuva).
  * Botão para limpar os dados quando quiser.

Interface feita com tkinter (já incluído no Python). Tema escuro com um
anel circular de progresso desenhado em um Canvas.
"""

from __future__ import annotations

import csv
import math
import os
import sys
import threading
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

import armazenamento as db
import bandeja
import notificacao
import sons


# --------------------------------------------------------------------------- #
# Paleta de cores (tema escuro "tomate")
# --------------------------------------------------------------------------- #
COR_FUNDO = "#1e2030"
COR_PAINEL = "#2b2f45"
COR_TEXTO = "#e7e8ee"
COR_TEXTO_FRACO = "#9aa0b5"
COR_FOCO = "#ff6b6b"      # vermelho-tomate
COR_INTERVALO = "#4ec9a6"  # verde-menta
COR_TRILHA = "#3a3e52"    # trilha do anel (fundo)
COR_BOTAO = "#3a3e52"
COR_BOTAO_ATIVO = "#4a4f68"
COR_SCROLL_TRILHA = "#252838"  # fundo da barra de rolagem (escuro)
COR_SCROLL = "#565c78"         # cursor da barra (claro, contrasta com a trilha)
COR_SCROLL_ATIVO = "#727a9c"   # cursor ao passar/arrastar (mais claro)
COR_DESTAQUE = "#f5a97f"       # âmbar: streak, meta e barra de hoje no gráfico

# Linhas alternadas (efeito "zebra") do combobox "No que você vai focar?":
# monocromático, alternando dois tons da MESMA cor — uma linha mais escura,
# a seguinte mais clara, e assim por diante. Fica elegante e fácil de
# percorrer sem poluir com cores diferentes. Ambos legíveis com texto claro.
COR_ITEM_ESCURO = "#363b57"    # tom mais escuro (indigo)
COR_ITEM_CLARO = "#484e73"     # tom mais claro (mesmo indigo)
COR_ITEM_TEXTO = "#f7f8fc"     # texto (claro) sobre as linhas

# Aba Jardim: terra dos canteiros onde as "plantas" (emojis) são fincadas.
COR_TERRA = "#7a5230"          # marrom da leira de terra
COR_TERRA_VAZIA = "#454a63"    # cova ainda sem planta (tom apagado)

FONTE = "Segoe UI"


def _clarear(cor: str, fator: float = 0.16) -> str:
    """Clareia uma cor #rrggbb misturando-a com branco (para efeitos hover)."""
    r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(
        min(255, int(c + (255 - c) * fator)) for c in (r, g, b)
    )


def _tingir(cor: str, fundo: str = COR_FUNDO, fator: float = 0.80) -> str:
    """Mistura uma cor viva com o fundo escuro, gerando um tom suave.

    Usado para dar aos botões um fundo levemente colorido (tingido) sem
    ofuscar a cor cheia do botão principal.
    """
    r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
    fr, fg, fb = (int(fundo[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (
        int(r + (fr - r) * fator),
        int(g + (fg - g) * fator),
        int(b + (fb - b) * fator),
    )

# Estados possíveis do ciclo.
FOCO = "foco"
INTERVALO_CURTO = "intervalo_curto"
INTERVALO_LONGO = "intervalo_longo"

# Ícones da barra de tarefas conforme o estado (resolvidos ao lado deste
# arquivo, para funcionar mesmo quando o app é aberto de outra pasta).
_PASTA = os.path.dirname(os.path.abspath(__file__))
ICONE_FOCO = os.path.join(_PASTA, "foco.ico")            # focando (vermelho)
ICONE_INTERVALO = os.path.join(_PASTA, "foco_intervalo.ico")  # intervalo (verde)
ICONE_OCIOSO = os.path.join(_PASTA, "foco_ocioso.ico")   # parado/pausado (cinza)


class FocoPomodoro:
    FILTRO_TODOS = "Todos os dias"
    FILTRO_TODAS_TAREFAS = "Todas as tarefas"
    ROTULO_DISP_PADRAO = "🔊 Padrão do Windows (segue o Windows)"

    # Aba Jardim -------------------------------------------------------- #
    # Flores usadas no nível "flor" do canteiro; a variedade é escolhida
    # pelo índice da planta, deixando o canteiro colorido e não repetitivo.
    PALETA_FLORES = ("🌷", "🌻", "🌸", "🌼", "🌹", "🌺")
    # Abreviações dos dias da semana (segunda=0 ... domingo=6), para rotular
    # as colunas da "floresta" dos últimos 7 dias.
    DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")

    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = db.carregar_config()

        # Ao abrir, já descarta registros de histórico além do limite salvo.
        db.podar_historico(self.config["dias_historico"])

        # Fixa a saída de áudio no dispositivo salvo (se houver). Vazio = segue
        # o dispositivo padrão do Windows, via winsound.
        dispositivo = self.config.get("dispositivo_audio", "")
        sons.definir_dispositivo(dispositivo or None)
        if dispositivo:
            sons.garantir_async()  # prepara o backend sem travar a abertura

        # Estado do timer ------------------------------------------------- #
        self.estado = FOCO
        self.rodando = False
        self.segundos_restantes = self.config["pomodoro_min"] * 60
        self.segundos_totais = self.segundos_restantes
        self.pomodoros_concluidos_sessao = 0
        self._job = None  # id do agendamento .after()
        self._prorrogacao = False  # True enquanto corre um "+5 min" extra

        self._icone_atual = None  # evita reaplicar o mesmo ícone à toa
        self.bandeja = bandeja.Bandeja(self)  # ícone na área de notificação
        self._montar_janela()
        self._montar_interface()
        self._atualizar_visor()
        self.bandeja.iniciar()
        self._atualizar_icone_bandeja()
        self._atualizar_aba_historico()

    # ===================================================================== #
    # Construção da janela e da interface
    # ===================================================================== #
    def _montar_janela(self) -> None:
        self.root.title("Foco Pomodoro")
        self.root.configure(bg=COR_FUNDO)

        # Tamanho fixo, centralizado na tela e sem permitir maximizar.
        # 500px de largura acomodam as 5 abas sem cortar e dão folga aos
        # cartões de estatísticas/jardim (valores longos como "227 min").
        largura, altura = 500, 660
        tela_l = self.root.winfo_screenwidth()
        tela_a = self.root.winfo_screenheight()
        x = (tela_l - largura) // 2
        y = (tela_a - altura) // 3  # um pouco acima do centro vertical
        self.root.geometry(f"{largura}x{altura}+{x}+{max(0, y)}")
        self.root.resizable(False, False)  # desativa redimensionar/maximizar

        # Estilo do Notebook (abas) para combinar com o tema escuro.
        estilo = ttk.Style()
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure("TNotebook", background=COR_FUNDO, borderwidth=0)
        estilo.configure(
            "TNotebook.Tab",
            background=COR_PAINEL,
            foreground=COR_TEXTO_FRACO,
            padding=(11, 8),  # horizontal enxuto p/ as 5 abas caberem inteiras
            font=(FONTE, 10, "bold"),
            borderwidth=0,
        )
        estilo.map(
            "TNotebook.Tab",
            background=[("selected", COR_FUNDO)],
            foreground=[("selected", COR_FOCO)],
        )

        # Barras de rolagem: cursor claro sobre trilha escura, para que
        # fique visível onde se está clicando (vale para todas as barras).
        for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            estilo.configure(
                orient,
                background=COR_SCROLL,           # cursor (parte que arrasta)
                troughcolor=COR_SCROLL_TRILHA,   # trilha de fundo
                bordercolor=COR_SCROLL_TRILHA,
                arrowcolor=COR_TEXTO_FRACO,
                relief="flat",
                borderwidth=0,
            )
            estilo.map(
                orient,
                background=[
                    ("pressed", COR_SCROLL_ATIVO),
                    ("active", COR_SCROLL_ATIVO),
                ],
            )

        # Combobox "No que você vai focar?": estilo próprio, mais encorpado e
        # colorido que o padrão. Campo em tom de painel, seta destacada em
        # tomate e borda que acende em âmbar ao receber foco. A altura vem da
        # fonte maior (definida no widget) somada ao padding daqui.
        estilo.configure(
            "Foco.TCombobox",
            fieldbackground=COR_PAINEL,
            background=COR_FOCO,        # área da seta
            foreground=COR_TEXTO,
            arrowcolor="#ffffff",
            arrowsize=18,
            bordercolor=COR_FOCO,
            lightcolor=COR_PAINEL,
            darkcolor=COR_PAINEL,
            relief="flat",
            padding=(8, 3),
        )
        estilo.map(
            "Foco.TCombobox",
            fieldbackground=[
                ("readonly", COR_PAINEL),
                ("disabled", COR_FUNDO),
            ],
            foreground=[("disabled", COR_TEXTO_FRACO)],
            background=[
                ("disabled", COR_BOTAO),
                ("active", "#ff8585"),
                ("pressed", "#ff8585"),
            ],
            arrowcolor=[("disabled", COR_TEXTO_FRACO)],
            bordercolor=[
                ("focus", COR_DESTAQUE),
                ("hover", COR_DESTAQUE),
            ],
        )

    def _atualizar_icone_bandeja(self) -> None:
        """Reflete o estado atual do timer em dois lugares, para sinalizar que
        o timer está em atividade e qual contagem corre:

          * o ícone na bandeja do sistema (área de notificação);
          * o ícone da janela/barra de tarefas (reforço visual).

        Estados:
          * focando        -> tomate vermelho (foco.ico)
          * intervalo      -> tomate verde    (foco_intervalo.ico)
          * parado/pausado -> tomate cinza    (foco_ocioso.ico)
        """
        if not self.rodando:
            estado, caminho = "ocioso", ICONE_OCIOSO
        elif self.estado == FOCO:
            estado, caminho = "foco", ICONE_FOCO
        else:
            estado, caminho = "intervalo", ICONE_INTERVALO

        # Ícone na bandeja do sistema (roda em thread própria; sempre seguro).
        self.bandeja.atualizar(estado)

        # Ícone da janela/barra de tarefas.
        if caminho == self._icone_atual:
            return  # já é o ícone certo; nada a fazer
        try:
            self.root.iconbitmap(caminho)
            self._icone_atual = caminho
        except tk.TclError:
            # Arquivo ausente/ inválido: mantém o ícone anterior sem quebrar.
            pass

    def _restaurar_da_bandeja(self) -> None:
        """Traz a janela de volta à frente (item 'Abrir' do menu da bandeja)."""
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(150, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    def encerrar(self) -> None:
        """Fecha o app com as mesmas checagens do botão de fechar da janela
        (avisa sobre config não salva e sobre timer em andamento)."""
        # Avisa se há configurações alteradas e ainda não salvas.
        if not self._tratar_config_pendente():
            return
        if self.rodando and not messagebox.askyesno(
            "Sair", "O timer está rodando. Deseja realmente sair?"
        ):
            return
        # Aproveita o tempo de um foco interrompido pelo fechamento.
        self._registrar_foco_parcial()
        self.bandeja.parar()
        self.root.destroy()

    def _sair_pela_bandeja(self) -> None:
        """Item 'Sair' do menu da bandeja (já devolvido à thread do tkinter)."""
        self.encerrar()

    def _montar_interface(self) -> None:
        self.abas = ttk.Notebook(self.root)
        self.abas.pack(fill="both", expand=True, padx=10, pady=10)

        self.aba_timer = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_historico = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_stats = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_jardim = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_config = tk.Frame(self.abas, bg=COR_FUNDO)

        self.abas.add(self.aba_timer, text="Timer")
        self.abas.add(self.aba_historico, text="Histórico")
        self.abas.add(self.aba_stats, text="Estatísticas")
        self.abas.add(self.aba_jardim, text="Jardim")
        self.abas.add(self.aba_config, text="Configurações")

        self._montar_aba_timer()
        self._montar_aba_historico()
        self._montar_aba_estatisticas()
        self._montar_aba_jardim()
        self._montar_aba_config()

        # Aviso de configurações não salvas ao sair da aba Configurações.
        self._idx_config = self.abas.index(self.aba_config)
        self._idx_stats = self.abas.index(self.aba_stats)
        self._idx_jardim = self.abas.index(self.aba_jardim)
        self._aba_atual = self.abas.index(self.abas.select())
        self.abas.bind("<<NotebookTabChanged>>", self._ao_trocar_aba, add="+")

    # --------------------------- Aba Timer ------------------------------ #
    def _montar_aba_timer(self) -> None:
        f = self.aba_timer

        self.lbl_estado = tk.Label(
            f, text="FOCO", font=(FONTE, 16, "bold"),
            fg=COR_FOCO, bg=COR_FUNDO,
        )
        self.lbl_estado.pack(pady=(18, 4))

        # Anel de progresso em um Canvas.
        self.tamanho_anel = 260
        self.canvas = tk.Canvas(
            f, width=self.tamanho_anel, height=self.tamanho_anel,
            bg=COR_FUNDO, highlightthickness=0,
        )
        self.canvas.pack(pady=6)

        margem = 18
        self.caixa_anel = (
            margem, margem,
            self.tamanho_anel - margem, self.tamanho_anel - margem,
        )
        # Trilha de fundo (círculo completo).
        self.canvas.create_arc(
            *self.caixa_anel, start=90, extent=359.999,
            style="arc", outline=COR_TRILHA, width=14,
        )
        # Arco de progresso (atualizado a cada tick).
        self.arco_progresso = self.canvas.create_arc(
            *self.caixa_anel, start=90, extent=0,
            style="arc", outline=COR_FOCO, width=14,
        )
        # Pontas arredondadas: dois círculos que acompanham o arco (o Canvas
        # não tem capstyle para arcos, então desenhamos as "tampas" à mão).
        self.raio_anel = (self.caixa_anel[2] - self.caixa_anel[0]) / 2
        self.cap_inicio = self.canvas.create_oval(
            0, 0, 0, 0, fill=COR_FOCO, width=0, state="hidden",
        )
        self.cap_fim = self.canvas.create_oval(
            0, 0, 0, 0, fill=COR_FOCO, width=0, state="hidden",
        )
        # Texto central com o tempo.
        centro = self.tamanho_anel / 2
        self.txt_tempo = self.canvas.create_text(
            centro, centro - 8, text="25:00",
            font=(FONTE, 44, "bold"), fill=COR_TEXTO,
        )
        self.txt_ciclo = self.canvas.create_text(
            centro, centro + 32, text="Pomodoro 1",
            font=(FONTE, 11), fill=COR_TEXTO_FRACO,
        )

        # Campo de descrição da tarefa.
        bloco = tk.Frame(f, bg=COR_FUNDO)
        bloco.pack(fill="x", padx=30, pady=(10, 6))
        tk.Label(
            bloco, text="🎯  No que você vai focar?",
            font=(FONTE, 12, "bold"), fg=COR_DESTAQUE, bg=COR_FUNDO,
        ).pack(anchor="w")
        # Combobox: itens vêm da lista salva em config.json e são gerenciados
        # na aba Configurações. "readonly" = só seleciona, não digita.
        # O visual (campo + lista colorida) vem do estilo "Foco.TCombobox" e
        # de _estilizar_dropdown_tarefa, chamado via postcommand ao abrir.
        self.var_tarefa = tk.StringVar()
        self.combo_tarefa = ttk.Combobox(
            bloco, textvariable=self.var_tarefa,
            values=self.config.get("tarefas", []),
            state="readonly", font=(FONTE, 12, "bold"),
            style="Foco.TCombobox", justify="center",
            postcommand=self._estilizar_dropdown_tarefa,
        )
        self.combo_tarefa.pack(fill="x", ipady=2, pady=(6, 0))
        # Restaura a última tarefa usada; se não existir mais, usa a primeira.
        tarefas = self.config.get("tarefas", [])
        ultima = self.config.get("tarefa_selecionada", "")
        if ultima in tarefas:
            self.var_tarefa.set(ultima)
        elif tarefas:
            self.combo_tarefa.current(0)
        # Sempre que o usuário trocar, guarda a escolha.
        self.combo_tarefa.bind(
            "<<ComboboxSelected>>", lambda e: self._salvar_tarefa_selecionada(),
        )

        # Botões de controle.
        botoes = tk.Frame(f, bg=COR_FUNDO)
        botoes.pack(pady=14)

        self.btn_iniciar = self._criar_botao(
            botoes, "▶  Iniciar", self.alternar_play_pause,
            cor=COR_FOCO, principal=True,
        )
        self.btn_iniciar.grid(row=0, column=0, padx=5)

        self._criar_botao(
            botoes, "⟳ Reiniciar", self.reiniciar_ciclo,
            tint=COR_DESTAQUE,
        ).grid(row=0, column=1, padx=5)

        self._criar_botao(
            botoes, "⏭ Pular", self.pular_ciclo,
            tint=COR_INTERVALO,
        ).grid(row=0, column=2, padx=5)

        self.lbl_sessao = tk.Label(
            f, text="Pomodoros nesta sessão: 0",
            font=(FONTE, 10), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        )
        self.lbl_sessao.pack(pady=(2, 0))

        # Progresso da meta diária (só aparece quando há meta configurada).
        self.lbl_meta = tk.Label(
            f, text="", font=(FONTE, 10, "bold"),
            fg=COR_DESTAQUE, bg=COR_FUNDO,
        )
        self.lbl_meta.pack(pady=(2, 10))
        self._atualizar_rotulo_meta()

    def _criar_botao(self, pai, texto, comando, cor=None, tint=None,
                     principal=False, padx=16, pady=10):
        # Três estilos:
        #  - principal: fundo cheio na cor (destaque máximo, ex.: Iniciar);
        #  - tint: fundo suave tingido + texto na cor viva (ex.: Reiniciar/Pular);
        #  - padrão: cinza neutro (demais botões do app).
        if principal:
            base = cor or COR_FOCO
            fg = fg_ativo = COR_FUNDO
            negrito = "bold"
        elif tint:
            base = _tingir(tint)
            fg = fg_ativo = tint
            negrito = "bold"
        else:
            base = cor or COR_BOTAO
            fg = fg_ativo = COR_TEXTO
            negrito = "normal"
        botao = tk.Button(
            pai, text=texto, command=comando,
            font=(FONTE, 11, negrito),
            fg=fg, bg=base,
            activebackground=_clarear(base),
            activeforeground=fg_ativo,
            relief="flat", bd=0, padx=padx, pady=pady, cursor="hand2",
        )
        # Hover: clareia o fundo enquanto o mouse está sobre o botão.
        hover = _clarear(base)
        botao.bind("<Enter>", lambda e: botao.config(bg=hover))
        botao.bind("<Leave>", lambda e: botao.config(bg=base))
        return botao

    # ------------------------- Aba Histórico ---------------------------- #
    def _montar_aba_historico(self) -> None:
        f = self.aba_historico

        # Cartões com os totais.
        cartoes = tk.Frame(f, bg=COR_FUNDO)
        cartoes.pack(fill="x", padx=14, pady=(16, 8))

        self.cartao_total_foco = self._criar_cartao(
            cartoes, "Tempo total de foco", "0 min",
        )
        self.cartao_total_foco.grid(row=0, column=0, padx=6, sticky="ew")

        self.cartao_qtd = self._criar_cartao(
            cartoes, "Pomodoros concluídos", "0",
        )
        self.cartao_qtd.grid(row=0, column=1, padx=6, sticky="ew")

        cartoes.columnconfigure(0, weight=1)
        cartoes.columnconfigure(1, weight=1)

        # Cabeçalho "Registros" com botões para editar/remover o selecionado.
        cab = tk.Frame(f, bg=COR_FUNDO)
        cab.pack(fill="x", padx=20, pady=(8, 4))
        tk.Label(
            cab, text="Registros", font=(FONTE, 12, "bold"),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        self._criar_botao(
            cab, "🗑 Remover", self._remover_registro, padx=10, pady=3,
        ).pack(side="right")
        self._criar_botao(
            cab, "✏ Editar", self._editar_registro, padx=10, pady=3,
        ).pack(side="right", padx=(0, 6))
        self._criar_botao(
            cab, "➕ Novo", self._adicionar_registro, padx=10, pady=3,
        ).pack(side="right", padx=(0, 6))

        # Linha de filtros: por dia e por tarefa.
        # O filtro por dia inicia no dia atual; o de tarefa em "todas".
        filtros = tk.Frame(f, bg=COR_FUNDO)
        filtros.pack(fill="x", padx=20, pady=(0, 4))

        # Filtro por dia (à esquerda).
        tk.Label(
            filtros, text="Dia:", font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        ).pack(side="left", padx=(0, 4))
        self.var_filtro_dia = tk.StringVar(value=date.today().isoformat())
        self.combo_filtro_dia = ttk.Combobox(
            filtros, textvariable=self.var_filtro_dia, values=[self.FILTRO_TODOS],
            state="readonly", width=13, font=(FONTE, 10),
        )
        self.combo_filtro_dia.pack(side="left")
        self.combo_filtro_dia.bind(
            "<<ComboboxSelected>>", lambda e: self._atualizar_aba_historico(),
        )

        # Filtro por tarefa (à direita).
        self.var_filtro_tarefa = tk.StringVar(value=self.FILTRO_TODAS_TAREFAS)
        self.combo_filtro_tarefa = ttk.Combobox(
            filtros, textvariable=self.var_filtro_tarefa,
            values=[self.FILTRO_TODAS_TAREFAS],
            state="readonly", width=14, font=(FONTE, 10),
        )
        self.combo_filtro_tarefa.pack(side="right")
        self.combo_filtro_tarefa.bind(
            "<<ComboboxSelected>>", lambda e: self._atualizar_aba_historico(),
        )
        tk.Label(
            filtros, text="Tarefa:", font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        ).pack(side="right", padx=(8, 4))

        # Tabela de registros.
        estilo = ttk.Style()
        estilo.configure(
            "Hist.Treeview", background=COR_PAINEL, fieldbackground=COR_PAINEL,
            foreground=COR_TEXTO, rowheight=26, borderwidth=0,
        )
        estilo.configure(
            "Hist.Treeview.Heading", background=COR_FUNDO,
            foreground=COR_TEXTO_FRACO, font=(FONTE, 9, "bold"),
            relief="flat",
        )
        estilo.map("Hist.Treeview.Heading", background=[("active", COR_FUNDO)])

        moldura = tk.Frame(f, bg=COR_PAINEL)
        moldura.pack(fill="both", expand=True, padx=14, pady=4)

        self.tabela = ttk.Treeview(
            moldura, columns=("data", "tarefa", "dur"),
            show="headings", style="Hist.Treeview",
        )
        self.tabela.heading("data", text="Data")
        self.tabela.heading("tarefa", text="Tarefa")
        self.tabela.heading("dur", text="Min")
        self.tabela.column("data", width=120, anchor="w")
        self.tabela.column("tarefa", width=180, anchor="w")
        self.tabela.column("dur", width=50, anchor="center")
        # Registros parciais (foco interrompido) aparecem esmaecidos.
        self.tabela.tag_configure("parcial", foreground=COR_TEXTO_FRACO)

        scroll = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=scroll.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Atalhos na tabela: duplo clique edita, Delete remove e o botão
        # direito abre um menu com as duas ações.
        self.menu_registro = tk.Menu(
            self.tabela, tearoff=0, bg=COR_PAINEL, fg=COR_TEXTO,
            activebackground=COR_FOCO, activeforeground=COR_FUNDO,
            font=(FONTE, 10), bd=0,
        )
        self.menu_registro.add_command(
            label="✏  Editar registro", command=self._editar_registro,
        )
        self.menu_registro.add_command(
            label="🗑  Remover registro", command=self._remover_registro,
        )

        def _abrir_menu(evento):
            iid = self.tabela.identify_row(evento.y)
            if iid:
                self.tabela.selection_set(iid)
                self.menu_registro.tk_popup(evento.x_root, evento.y_root)

        def _duplo_clique(evento):
            if self.tabela.identify_row(evento.y):
                self._editar_registro()

        self.tabela.bind("<Button-3>", _abrir_menu)
        self.tabela.bind("<Double-1>", _duplo_clique)
        self.tabela.bind("<Delete>", lambda e: self._remover_registro())

        botoes_hist = tk.Frame(f, bg=COR_FUNDO)
        botoes_hist.pack(pady=12)
        self._criar_botao(
            botoes_hist, "⬇  Exportar CSV", self.exportar_csv,
        ).pack(side="left", padx=5)
        self._criar_botao(
            botoes_hist, "🗑  Limpar todos os dados", self.limpar_dados,
        ).pack(side="left", padx=5)

    def _criar_cartao(self, pai, titulo, valor, cor=COR_FOCO):
        cartao = tk.Frame(pai, bg=COR_PAINEL)
        # Filete colorido no topo, dá identidade a cada métrica.
        tk.Frame(cartao, bg=cor, height=3).pack(fill="x")
        tk.Label(
            cartao, text=titulo, font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_PAINEL,
        ).pack(anchor="w", padx=14, pady=(10, 0))
        lbl_valor = tk.Label(
            cartao, text=valor, font=(FONTE, 18, "bold"),
            fg=cor, bg=COR_PAINEL,
        )
        lbl_valor.pack(anchor="w", padx=14, pady=(0, 12))
        cartao.lbl_valor = lbl_valor  # guarda referência para atualizar
        cartao.fonte_base = 18        # tamanho ideal; encolhe se não couber
        # Reencaixa o valor sempre que o cartão muda de largura (ex.: ao abrir
        # a aba pela 1ª vez, quando a largura real passa a ser conhecida).
        cartao.bind(
            "<Configure>", lambda e, c=cartao: self._ajustar_valor_cartao(c),
        )
        return cartao

    def _ajustar_valor_cartao(self, cartao) -> None:
        """Encolhe a fonte do valor do cartão até caber na largura disponível,
        para números grandes (ex.: '365 dias', '1234 min') nunca ficarem
        cortados. Não passa da fonte-base nem encolhe abaixo de 11."""
        lbl = cartao.lbl_valor
        disp = cartao.winfo_width() - 2 * 14  # desconta o padx do rótulo
        if disp <= 1:
            return  # ainda sem layout; o <Configure> chama de novo com a largura real
        texto = lbl.cget("text")
        tam = getattr(cartao, "fonte_base", 18)
        medidor = tkfont.Font(family=FONTE, size=tam, weight="bold")
        while tam > 11 and medidor.measure(texto) > disp:
            tam -= 1
            medidor.configure(size=tam)
        lbl.config(font=(FONTE, tam, "bold"))

    def _definir_valor_cartao(self, cartao, texto: str) -> None:
        """Atualiza o valor de um cartão e reencaixa a fonte automaticamente."""
        cartao.lbl_valor.config(text=texto)
        self._ajustar_valor_cartao(cartao)

    # ------------------------ Aba Estatísticas -------------------------- #
    DIAS_GRAFICO = 14

    def _montar_aba_estatisticas(self) -> None:
        f = self.aba_stats

        cartoes = tk.Frame(f, bg=COR_FUNDO)
        cartoes.pack(fill="x", padx=14, pady=(16, 8))

        self.cartao_streak = self._criar_cartao(
            cartoes, "🔥 Sequência", "0 dias", cor=COR_DESTAQUE,
        )
        self.cartao_streak.grid(row=0, column=0, padx=6, sticky="nsew")
        self.cartao_hoje = self._criar_cartao(
            cartoes, "🍅 Hoje", "0", cor=COR_FOCO,
        )
        self.cartao_hoje.grid(row=0, column=1, padx=6, sticky="nsew")
        self.cartao_media = self._criar_cartao(
            cartoes, "⏱ Média/dia", "0 min", cor=COR_INTERVALO,
        )
        self.cartao_media.grid(row=0, column=2, padx=6, sticky="nsew")
        for c in range(3):
            cartoes.columnconfigure(c, weight=1, uniform="cards")

        tk.Label(
            f, text=f"Minutos de foco — últimos {self.DIAS_GRAFICO} dias",
            font=(FONTE, 12, "bold"), fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", padx=20, pady=(14, 4))

        moldura = tk.Frame(f, bg=COR_PAINEL)
        moldura.pack(fill="x", padx=14)
        self.canvas_grafico = tk.Canvas(
            moldura, width=400, height=250,
            bg=COR_PAINEL, highlightthickness=0,
        )
        self.canvas_grafico.pack(padx=6, pady=6)

        tk.Label(
            f,
            text=("A barra de hoje aparece em âmbar. Registros parciais (◐) "
                  "contam nos minutos, mas não na meta nem na sequência."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=400,
        ).pack(anchor="w", padx=20, pady=(8, 0))

        self._atualizar_estatisticas()

    def _atualizar_estatisticas(self) -> None:
        """Recalcula cartões e redesenha o gráfico com o histórico atual."""
        dados = db.minutos_por_dia(self.DIAS_GRAFICO)

        streak = db.calcular_streak()
        self._definir_valor_cartao(
            self.cartao_streak, f"{streak} dia" + ("" if streak == 1 else "s"),
        )

        meta = int(self.config.get("meta_pomodoros_dia", 0) or 0)
        feitos = db.pomodoros_do_dia()
        self._definir_valor_cartao(
            self.cartao_hoje, f"{feitos} / {meta}" if meta > 0 else str(feitos),
        )

        media = sum(dados.values()) / max(1, len(dados))
        self._definir_valor_cartao(self.cartao_media, f"{round(media)} min")

        self._desenhar_grafico(dados)

    def _desenhar_grafico(self, dados: dict[str, int]) -> None:
        """Gráfico de barras (minutos por dia) desenhado direto no Canvas."""
        cv = self.canvas_grafico
        cv.delete("all")
        larg = int(cv["width"])
        alt = int(cv["height"])
        m_esq, m_dir, m_topo, m_base = 10, 10, 26, 30
        area_a = alt - m_topo - m_base
        y_base = m_topo + area_a

        meta_min = (
            int(self.config.get("meta_pomodoros_dia", 0) or 0)
            * self.config["pomodoro_min"]
        )
        maximo = max(max(dados.values(), default=0), meta_min, 1)

        # Linha de base.
        cv.create_line(m_esq, y_base, larg - m_dir, y_base, fill=COR_TRILHA)

        # Linha tracejada da meta diária convertida em minutos.
        if meta_min > 0:
            y_meta = m_topo + area_a * (1 - meta_min / maximo)
            cv.create_line(
                m_esq, y_meta, larg - m_dir, y_meta,
                fill=COR_INTERVALO, dash=(4, 4),
            )
            cv.create_text(
                larg - m_dir, y_meta - 8, text=f"meta {meta_min} min",
                anchor="e", fill=COR_INTERVALO, font=(FONTE, 8),
            )

        hoje = date.today().isoformat()
        n = max(1, len(dados))
        passo = (larg - m_esq - m_dir) / n
        larg_barra = min(22, passo * 0.62)

        for i, (dia, minutos) in enumerate(dados.items()):
            cx = m_esq + passo * (i + 0.5)
            e_hoje = dia == hoje
            if minutos > 0:
                h = max(3, area_a * minutos / maximo)
                cv.create_rectangle(
                    cx - larg_barra / 2, y_base - h,
                    cx + larg_barra / 2, y_base,
                    fill=COR_DESTAQUE if e_hoje else COR_FOCO, width=0,
                )
                cv.create_text(
                    cx, y_base - h - 9, text=str(minutos),
                    fill=COR_TEXTO if e_hoje else COR_TEXTO_FRACO,
                    font=(FONTE, 7),
                )
            else:
                # Dia sem foco: traço apagado para marcar a posição.
                cv.create_rectangle(
                    cx - larg_barra / 2, y_base - 2,
                    cx + larg_barra / 2, y_base,
                    fill=COR_TRILHA, width=0,
                )
            cv.create_text(
                cx, y_base + 12, text=dia[8:10],
                fill=COR_TEXTO if e_hoje else COR_TEXTO_FRACO, font=(FONTE, 8),
            )

    def _atualizar_rotulo_meta(self) -> None:
        """Mostra o progresso da meta diária na aba Timer (se houver meta)."""
        meta = int(self.config.get("meta_pomodoros_dia", 0) or 0)
        if meta <= 0:
            self.lbl_meta.config(text="")
            return
        feitos = db.pomodoros_do_dia()
        icone = "🏆" if feitos >= meta else "🍅"
        self.lbl_meta.config(text=f"Meta de hoje: {icone} {feitos} / {meta}")

    # --------------------------- Aba Jardim ----------------------------- #
    #
    # Um jardim que cresce sozinho a partir do histórico: cada pomodoro
    # concluído "planta" uma muda no canteiro de hoje e a floresta mostra os
    # últimos 7 dias. Nada é gravado a mais — tudo é derivado do que já existe
    # em historico.json (mesmos números da aba Estatísticas). As "plantas" são
    # emojis desenhados sobre leiras de terra (retângulos/óvalos simples), sem
    # depender de imagens nem de internet.

    NIVEIS_JARDIM = ("Brotos 🌱", "Ervas 🌿", "Flores 🌷", "Árvores 🌳")

    def _nivel_jardim(self, streak: int) -> int:
        """Nível de maturação do jardim conforme a sequência de dias (streak):
        0=broto, 1=erva, 2=flor, 3=árvore. Quanto mais firme o hábito, mais
        maduras nascem as plantas do dia."""
        if streak <= 1:
            return 0
        if streak <= 3:
            return 1
        if streak <= 6:
            return 2
        return 3

    def _planta_hoje(self, indice: int, nivel: int) -> str:
        """Emoji de uma planta do canteiro de hoje, dado seu índice e o nível
        atual do jardim. No nível 'flor', varia a espécie pelo índice para o
        canteiro ficar colorido e variado."""
        if nivel == 0:
            return "🌱"
        if nivel == 1:
            return "🌿"
        if nivel == 2:
            return self.PALETA_FLORES[indice % len(self.PALETA_FLORES)]
        return "🌳"

    def _planta_por_pomodoros(self, pomodoros: int) -> str:
        """Planta que representa um dia inteiro na floresta: quanto mais
        pomodoros naquele dia, mais madura a planta (vazio = terra nua)."""
        if pomodoros <= 0:
            return ""
        if pomodoros == 1:
            return "🌱"
        if pomodoros == 2:
            return "🌿"
        if pomodoros <= 4:
            return "🌷"
        if pomodoros <= 6:
            return "🌻"
        return "🌳"

    def _montar_aba_jardim(self) -> None:
        wrap = self._frame_rolavel(self.aba_jardim)

        # Cartões-resumo (mesmo estilo das outras abas).
        cartoes = tk.Frame(wrap, bg=COR_FUNDO)
        cartoes.pack(fill="x", padx=14, pady=(16, 8))
        self.cartao_jardim_hoje = self._criar_cartao(
            cartoes, "🌱 Plantas hoje", "0", cor=COR_INTERVALO,
        )
        self.cartao_jardim_hoje.grid(row=0, column=0, padx=6, sticky="nsew")
        self.cartao_jardim_streak = self._criar_cartao(
            cartoes, "🔥 Sequência", "0 dias", cor=COR_DESTAQUE,
        )
        self.cartao_jardim_streak.grid(row=0, column=1, padx=6, sticky="nsew")
        self.cartao_jardim_total = self._criar_cartao(
            cartoes, "🌳 Colheita total", "0", cor=COR_FOCO,
        )
        self.cartao_jardim_total.grid(row=0, column=2, padx=6, sticky="nsew")
        for c in range(3):
            cartoes.columnconfigure(c, weight=1, uniform="jardim")

        # Frase de estado (muda conforme meta batida / canteiro vazio).
        self.lbl_jardim_status = tk.Label(
            wrap, text="", font=(FONTE, 11, "bold"),
            fg=COR_INTERVALO, bg=COR_FUNDO, justify="left", wraplength=330,
        )
        self.lbl_jardim_status.pack(anchor="w", padx=20, pady=(10, 2))

        # Canteiro de hoje: uma muda por pomodoro concluído hoje.
        # Os canvases usam fill="x" e se redesenham conforme a largura real da
        # aba (via <Configure>), então nada é cortado, seja qual for o espaço.
        tk.Label(
            wrap, text="🌻 Canteiro de hoje", font=(FONTE, 12, "bold"),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", padx=20, pady=(8, 4))
        moldura_c = tk.Frame(wrap, bg=COR_PAINEL)
        moldura_c.pack(fill="x", padx=14)
        self.canvas_canteiro = tk.Canvas(
            moldura_c, height=90, bg=COR_PAINEL, highlightthickness=0,
        )
        self.canvas_canteiro.pack(fill="x", padx=6, pady=6)
        self.canvas_canteiro.bind("<Configure>", self._ao_redimensionar_canteiro)

        # Floresta: um resumo dos últimos 7 dias, uma planta por dia.
        tk.Label(
            wrap, text="🌳 Sua floresta — últimos 7 dias", font=(FONTE, 12, "bold"),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", padx=20, pady=(14, 4))
        moldura_f = tk.Frame(wrap, bg=COR_PAINEL)
        moldura_f.pack(fill="x", padx=14)
        self.canvas_floresta = tk.Canvas(
            moldura_f, height=110, bg=COR_PAINEL, highlightthickness=0,
        )
        self.canvas_floresta.pack(fill="x", padx=6, pady=6)
        self.canvas_floresta.bind("<Configure>", self._ao_redimensionar_floresta)

        tk.Label(
            wrap,
            text=("Cada pomodoro concluído planta uma muda no canteiro de hoje. "
                  "Quanto maior sua sequência (🔥), mais as plantas amadurecem: "
                  "🌱 broto → 🌿 erva → 🌷 flor → 🌳 árvore. Focos interrompidos "
                  "viram 🥀 e bater a meta do dia faz o canteiro florescer ☀️."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=330,
        ).pack(anchor="w", padx=20, pady=(10, 16))

        self._atualizar_aba_jardim()

    def _atualizar_aba_jardim(self) -> None:
        """Recalcula cartões, frase de estado e redesenha os dois canteiros a
        partir do histórico atual. Seguro chamar a qualquer momento (ignora
        silenciosamente se a aba ainda não foi montada)."""
        if not hasattr(self, "canvas_canteiro"):
            return

        historico = db.carregar_historico()
        hoje = date.today()
        hoje_iso = hoje.isoformat()

        completos_hoje = sum(
            1 for r in historico
            if str(r.get("data", ""))[:10] == hoje_iso and not r.get("parcial")
        )
        parciais_hoje = sum(
            1 for r in historico
            if str(r.get("data", ""))[:10] == hoje_iso and r.get("parcial")
        )
        total = sum(1 for r in historico if not r.get("parcial"))
        streak = db.calcular_streak()
        meta = int(self.config.get("meta_pomodoros_dia", 0) or 0)

        # Cartões.
        self._definir_valor_cartao(self.cartao_jardim_hoje, str(completos_hoje))
        self._definir_valor_cartao(
            self.cartao_jardim_streak, f"{streak} dia" + ("" if streak == 1 else "s"),
        )
        self._definir_valor_cartao(self.cartao_jardim_total, str(total))

        # Frase de estado / colheita.
        nivel = self._nivel_jardim(streak)
        nome_nivel = self.NIVEIS_JARDIM[nivel]
        if meta > 0 and completos_hoje >= meta:
            self.lbl_jardim_status.config(
                text=f"☀️ Canteiro florido! Meta batida — hoje o jardim está em {nome_nivel}.",
                fg=COR_DESTAQUE,
            )
        elif completos_hoje > 0:
            falta = f" · faltam {meta - completos_hoje} p/ a meta" if meta > completos_hoje else ""
            self.lbl_jardim_status.config(
                text=f"🌱 {completos_hoje} planta(s) hoje — nível {nome_nivel}{falta}.",
                fg=COR_INTERVALO,
            )
        else:
            self.lbl_jardim_status.config(
                text="🌰 Canteiro vazio. Conclua um foco para plantar sua primeira muda!",
                fg=COR_TEXTO_FRACO,
            )

        # Dados da floresta (últimos 7 dias), calculados do mesmo histórico.
        semana = []
        for i in range(6, -1, -1):
            dia = hoje - timedelta(days=i)
            dia_iso = dia.isoformat()
            pom = sum(
                1 for r in historico
                if str(r.get("data", ""))[:10] == dia_iso and not r.get("parcial")
            )
            semana.append((dia, pom))

        # Guarda os números para o redesenho responsivo (<Configure>) poder
        # reaproveitá-los sem reler o histórico a cada evento de tamanho.
        self._jardim_dados = {
            "completos": completos_hoje, "parciais": parciais_hoje,
            "streak": streak, "meta": meta, "semana": semana,
        }
        self._desenhar_canteiro(completos_hoje, parciais_hoje, streak, meta)
        self._desenhar_floresta(semana)

    def _ao_redimensionar_canteiro(self, evento) -> None:
        """Redesenha o canteiro quando a largura da aba muda (só na mudança de
        largura — mudar a altura do canvas não dispara um novo desenho)."""
        if getattr(self, "_larg_canteiro", None) == evento.width:
            return
        self._larg_canteiro = evento.width
        dados = getattr(self, "_jardim_dados", None)
        if dados:
            self._desenhar_canteiro(
                dados["completos"], dados["parciais"],
                dados["streak"], dados["meta"],
            )

    def _ao_redimensionar_floresta(self, evento) -> None:
        """Redesenha a floresta quando a largura da aba muda."""
        if getattr(self, "_larg_floresta", None) == evento.width:
            return
        self._larg_floresta = evento.width
        dados = getattr(self, "_jardim_dados", None)
        if dados:
            self._desenhar_floresta(dados["semana"])

    def _desenhar_canteiro(
        self, completos: int, parciais: int, streak: int, meta: int,
    ) -> None:
        """Desenha o canteiro de hoje: uma muda por pomodoro concluído, os
        focos parciais como 🥀 e as covas ainda vazias até a meta como '·'.
        A altura do canvas se ajusta ao número de linhas."""
        cv = self.canvas_canteiro
        larg = cv.winfo_width()
        if larg <= 1:
            return  # ainda sem layout; o <Configure> redesenha com a largura real
        cv.delete("all")
        nivel = self._nivel_jardim(streak)

        # Lista de itens a plantar: (emoji, cor). Concluídos, depois parciais.
        itens: list[tuple[str, str]] = [
            (self._planta_hoje(i, nivel), COR_TEXTO) for i in range(completos)
        ]
        itens += [("🥀", COR_TEXTO_FRACO) for _ in range(parciais)]
        vazios = max(0, meta - completos)  # covas restantes até a meta

        # 'lado' é uma margem lateral de folga: os glifos de emoji ocupam uma
        # caixa larga, então reservamos esse respiro para nada encostar/vazar
        # na borda (nem no dia mais à direita).
        cel, fileira, lado = 34, 42, 20
        cols = max(1, int((larg - 2 * lado) // cel))
        total = len(itens) + vazios

        if total == 0:
            cv.config(height=64)
            cv.create_text(
                larg / 2, 32, text="🌰  plante seu primeiro foco",
                font=(FONTE, 11), fill=COR_TEXTO_FRACO,
            )
            return

        linhas = math.ceil(total / cols)
        cv.config(height=linhas * fileira + 12)
        # Centraliza a grade (a última coluna preenchida pode não fechar a largura).
        usados = min(cols, total)
        margem_x = (larg - usados * cel) / 2 + cel / 2

        # Um sol no canto quando a meta do dia foi batida (ancorado pela
        # direita para o glifo largo não vazar a borda).
        if meta > 0 and completos >= meta:
            cv.create_text(larg - 6, 4, text="☀️", font=(FONTE, 12), anchor="ne")

        for idx in range(total):
            col, lin = idx % cols, idx // cols
            x = margem_x + col * cel
            y_base = 8 + lin * fileira + fileira - 14
            # Leira de terra (óvalo marrom) onde a planta é fincada.
            if idx < len(itens):
                emoji, cor = itens[idx]
                cv.create_oval(
                    x - 11, y_base - 4, x + 11, y_base + 4,
                    fill=COR_TERRA, width=0,
                )
                cv.create_text(x, y_base - 12, text=emoji, font=(FONTE, 14), fill=cor)
            else:
                cv.create_oval(
                    x - 10, y_base - 3, x + 10, y_base + 3,
                    fill=COR_TERRA_VAZIA, width=0,
                )
                cv.create_text(
                    x, y_base - 11, text="·", font=(FONTE, 15), fill=COR_TEXTO_FRACO,
                )

    def _desenhar_floresta(self, semana: list[tuple[date, int]]) -> None:
        """Desenha a floresta dos últimos 7 dias: uma planta por dia (maior
        conforme mais pomodoros), com o dia de hoje destacado em âmbar."""
        cv = self.canvas_floresta
        larg = cv.winfo_width()
        if larg <= 1:
            return  # ainda sem layout; o <Configure> redesenha com a largura real
        cv.delete("all")
        alt = int(cv["height"])
        hoje = date.today()

        n = max(1, len(semana))
        passo = larg / n
        y_base = alt - 26
        # Leira e planta se ajustam ao espaço de cada coluna (para caber os 7 dias).
        raio_x = min(15, passo / 2 - 3)

        for i, (dia, pom) in enumerate(semana):
            cx = passo * (i + 0.5)
            e_hoje = dia == hoje
            # Contagem acima da planta.
            if pom > 0:
                cv.create_text(
                    cx, y_base - 36, text=str(pom), font=(FONTE, 8),
                    fill=COR_TEXTO if e_hoje else COR_TEXTO_FRACO,
                )
            # Planta do dia (ou terra nua).
            emoji = self._planta_por_pomodoros(pom)
            if emoji:
                cv.create_text(cx, y_base - 18, text=emoji, font=(FONTE, 18))
            else:
                cv.create_text(
                    cx, y_base - 15, text="·", font=(FONTE, 16), fill=COR_TEXTO_FRACO,
                )
            # Leira de terra (âmbar no dia de hoje).
            cv.create_oval(
                cx - raio_x, y_base - 5, cx + raio_x, y_base + 5,
                fill=COR_DESTAQUE if e_hoje else COR_TERRA, width=0,
            )
            # Rótulo: dia da semana + número do dia.
            rotulo = f"{self.DIAS_SEMANA[dia.weekday()]} {dia.day:02d}"
            cv.create_text(
                cx, alt - 10, text=rotulo, font=(FONTE, 8),
                fill=COR_TEXTO if e_hoje else COR_TEXTO_FRACO,
            )

    # ------------------------ Aba Configurações ------------------------- #
    def _montar_aba_config(self) -> None:
        wrap = self._frame_rolavel(self.aba_config)

        self.var_pomodoro = tk.IntVar(value=self.config["pomodoro_min"])
        self.var_intervalo = tk.IntVar(value=self.config["intervalo_min"])
        self.var_intervalo_longo = tk.IntVar(value=self.config["intervalo_longo_min"])
        self.var_ate_longo = tk.IntVar(value=self.config["pomodoros_ate_intervalo_longo"])
        self.var_usar_intervalos = tk.BooleanVar(value=self.config["usar_intervalos"])
        self.var_som = tk.BooleanVar(value=self.config["som_ao_terminar"])
        self.var_volume = tk.IntVar(value=self.config["volume"])
        self.var_som_pomodoro = tk.StringVar(value=self.config["som_fim_pomodoro"])
        self.var_som_intervalo = tk.StringVar(value=self.config["som_fim_intervalo"])
        self.var_bipe = tk.BooleanVar(value=self.config["bipe_contagem_regressiva"])
        self.var_notificacao = tk.BooleanVar(value=self.config["notificacao_windows"])
        self.var_aviso_central = tk.BooleanVar(value=self.config["aviso_central"])
        self.var_dias_historico = tk.StringVar(value=str(self.config["dias_historico"]))
        self.var_auto_iniciar = tk.BooleanVar(value=self.config["auto_iniciar"])
        self.var_prorrogacao_min = tk.IntVar(value=self.config["prorrogacao_min"])
        self.var_som_ambiente = tk.StringVar(value=self.config["som_ambiente"])
        self.var_meta = tk.IntVar(value=self.config["meta_pomodoros_dia"])
        # Dispositivo de saída fixo: guardamos o VALOR bruto ("" = padrão do
        # Windows; caso contrário, o nome do dispositivo). O combobox mostra
        # rótulos e mapeia de volta para estes valores em self._disp_valores.
        self._disp_valor = self.config.get("dispositivo_audio", "")
        self._disp_valores: list[str] = [""]
        self._disp_nomes_cache: list[str] = []

        # ---- Tempos ----
        self._titulo_secao(wrap, "⏱  Tempos")
        self._linha_spin(wrap, "Duração do foco (min)", self.var_pomodoro, 1, 180)
        self._linha_spin(wrap, "Intervalo curto (min)", self.var_intervalo, 1, 60)
        self._linha_spin(wrap, "Intervalo longo (min)", self.var_intervalo_longo, 1, 90)
        self._linha_spin(wrap, "Pomodoros até intervalo longo", self.var_ate_longo, 1, 12)
        self._linha_spin(wrap, "Prorrogação do foco (min)", self.var_prorrogacao_min, 1, 60)
        self._linha_check(
            wrap, "Usar intervalos (desmarque p/ pomodoros seguidos)",
            self.var_usar_intervalos,
        )
        self._linha_check(
            wrap, "Iniciar o próximo ciclo automaticamente",
            self.var_auto_iniciar,
        )

        # ---- Meta diária ----
        self._titulo_secao(wrap, "🎯  Meta diária")
        self._linha_spin(wrap, "Pomodoros por dia (0 = sem meta)", self.var_meta, 0, 48)
        tk.Label(
            wrap,
            text=("Com uma meta definida, a aba Timer mostra o progresso do "
                  "dia e você recebe um aviso ao completá-la."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 4))

        # ---- Sons ----
        self._titulo_secao(wrap, "🔊  Sons e volume")
        self._linha_check(wrap, "Ativar alertas sonoros", self.var_som)

        # Volume próprio (independente do Windows).
        linha_vol = tk.Frame(wrap, bg=COR_FUNDO)
        linha_vol.pack(fill="x", pady=5)
        tk.Label(
            linha_vol, text="Volume", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        self.lbl_volume = tk.Label(
            linha_vol, text=f"{self.var_volume.get()}%", font=(FONTE, 10, "bold"),
            fg=COR_INTERVALO, bg=COR_FUNDO, width=5,
        )
        self.lbl_volume.pack(side="right")
        escala = tk.Scale(
            linha_vol, from_=0, to=100, orient="horizontal",
            variable=self.var_volume, showvalue=False,
            bg=COR_INTERVALO,            # cor do botão deslizante (verde, bem visível)
            troughcolor=COR_TRILHA,      # trilha de fundo (escura, faz contraste)
            activebackground=COR_TEXTO,  # botão clareia ao arrastar
            highlightthickness=0, bd=0, sliderrelief="raised",
            sliderlength=24, width=14, length=180,
            command=lambda v: self.lbl_volume.config(text=f"{int(float(v))}%"),
        )
        escala.pack(side="right", padx=10)

        self._linha_som(wrap, "Som ao fim do pomodoro", self.var_som_pomodoro)
        self._linha_som(wrap, "Som ao fim do intervalo", self.var_som_intervalo)
        self._linha_check(
            wrap, "Bipe nos últimos 3 segundos do ciclo", self.var_bipe,
        )

        # Som ambiente contínuo durante o foco, com botões de prévia.
        linha_amb = tk.Frame(wrap, bg=COR_FUNDO)
        linha_amb.pack(fill="x", pady=5)
        tk.Label(
            linha_amb, text="Som ambiente durante o foco", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        self._criar_botao(
            linha_amb, "⏹", sons.parar_ambiente,
        ).pack(side="right", padx=(4, 0))
        self._criar_botao(
            linha_amb, "▶",
            lambda: sons.tocar_ambiente(
                self.var_som_ambiente.get(), self.var_volume.get()),
        ).pack(side="right", padx=(6, 0))
        ttk.Combobox(
            linha_amb, textvariable=self.var_som_ambiente,
            values=sons.NOMES_AMBIENTES, state="readonly",
            width=12, font=(FONTE, 10),
        ).pack(side="right")
        tk.Label(
            wrap,
            text=("O ambiente toca em loop enquanto o foco corre e para nos "
                  "intervalos. Com ele ativo, o bipe dos últimos segundos do "
                  "foco é desativado (limitação de som do Windows)."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 4))

        # ---- Dispositivo de saída ----
        self._titulo_secao(wrap, "🎧  Dispositivo de saída")
        tk.Label(
            wrap,
            text=("Escolha por qual dispositivo o app toca TODOS os sons. "
                  "Assim o áudio fica fixo nele mesmo que você troque o "
                  "dispositivo padrão do Windows (ex.: ao pôr o fone para "
                  "falar com alguém)."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 6))

        linha_disp = tk.Frame(wrap, bg=COR_FUNDO)
        linha_disp.pack(fill="x", pady=5)
        tk.Label(
            linha_disp, text="Sair o som por", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        self._criar_botao(
            linha_disp, "▶", self._testar_dispositivo, padx=10, pady=3,
        ).pack(side="right", padx=(6, 0))
        self._criar_botao(
            linha_disp, "🔄", self._recarregar_dispositivos, padx=10, pady=3,
        ).pack(side="right", padx=(6, 0))
        self.combo_dispositivo = ttk.Combobox(
            linha_disp, state="readonly", width=24, font=(FONTE, 10),
        )
        self.combo_dispositivo.pack(side="right")
        self.combo_dispositivo.bind(
            "<<ComboboxSelected>>", lambda e: self._ao_escolher_dispositivo(),
        )
        self.lbl_disp_aviso = tk.Label(
            wrap, text="", font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        )
        self.lbl_disp_aviso.pack(anchor="w", pady=(0, 2))
        # Carrega a lista de dispositivos em segundo plano (pode instalar/consultar).
        self._popular_dispositivos()

        # ---- Notificações ----
        self._titulo_secao(wrap, "🔔  Notificações")
        self._linha_check(
            wrap, "Mostrar notificação do Windows ao terminar",
            self.var_notificacao,
        )
        self._linha_check(
            wrap, "Mostrar aviso GRANDE no centro da tela (fica fixo até fechar)",
            self.var_aviso_central,
        )
        botoes_notif = tk.Frame(wrap, bg=COR_FUNDO)
        botoes_notif.pack(anchor="w", pady=(2, 6))
        self._criar_botao(
            botoes_notif, "Testar notificação",
            lambda: notificacao.notificar(
                "Foco Pomodoro", "Exemplo de notificação 🍅"),
        ).pack(side="left")
        self._criar_botao(
            botoes_notif, "Testar aviso central",
            lambda: self._mostrar_aviso_central(
                "Pomodoro concluído! 🍅", "Exemplo de aviso central.", COR_FOCO),
        ).pack(side="left", padx=(8, 0))

        # ---- Histórico ----
        self._titulo_secao(wrap, "🗂  Histórico")
        linha_hist = tk.Frame(wrap, bg=COR_FUNDO)
        linha_hist.pack(fill="x", pady=5)
        tk.Label(
            linha_hist, text="Manter histórico dos últimos", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        tk.Label(
            linha_hist, text="dias", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="right")
        ttk.Combobox(
            linha_hist, textvariable=self.var_dias_historico,
            values=["30", "60", "120"], state="readonly",
            width=5, font=(FONTE, 10), justify="center",
        ).pack(side="right", padx=6)
        tk.Label(
            wrap,
            text=("Registros mais antigos que esse limite são apagados "
                  "automaticamente para não pesar o arquivo."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 4))

        # ---- Tarefas de foco (itens do combobox) ----
        self._titulo_secao(wrap, "📝  Tarefas de foco (lista do combobox)")
        tk.Label(
            wrap,
            text=("Os itens abaixo aparecem no combobox da aba Timer. "
                  "Adicione quantos quiser; tudo fica salvo automaticamente."),
            font=(FONTE, 9), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 6))

        moldura_t = tk.Frame(wrap, bg=COR_PAINEL)
        moldura_t.pack(fill="x", pady=(0, 6))
        self.lista_tarefas = tk.Listbox(
            moldura_t, height=5, font=(FONTE, 10),
            bg=COR_PAINEL, fg=COR_TEXTO, relief="flat",
            selectbackground=COR_FOCO, selectforeground=COR_FUNDO,
            highlightthickness=0, activestyle="none", bd=0,
        )
        scroll_t = ttk.Scrollbar(
            moldura_t, orient="vertical", command=self.lista_tarefas.yview,
        )
        self.lista_tarefas.configure(yscrollcommand=scroll_t.set)
        self.lista_tarefas.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        scroll_t.pack(side="right", fill="y")

        linha_add = tk.Frame(wrap, bg=COR_FUNDO)
        linha_add.pack(fill="x", pady=(0, 2))
        self.entrada_nova_tarefa = tk.Entry(
            linha_add, font=(FONTE, 11), bg=COR_PAINEL, fg=COR_TEXTO,
            insertbackground=COR_TEXTO, relief="flat",
            highlightthickness=1, highlightbackground=COR_TRILHA,
            highlightcolor=COR_FOCO,
        )
        self.entrada_nova_tarefa.pack(side="left", fill="x", expand=True, ipady=5)
        self.entrada_nova_tarefa.bind("<Return>", lambda e: self._adicionar_tarefa())
        self._criar_botao(
            linha_add, "➕ Adicionar", self._adicionar_tarefa,
        ).pack(side="left", padx=(6, 0))

        linha_gerir = tk.Frame(wrap, bg=COR_FUNDO)
        linha_gerir.pack(anchor="w", pady=(2, 0))
        self._criar_botao(
            linha_gerir, "✏ Renomear", self._renomear_tarefa,
        ).pack(side="left")
        self._criar_botao(
            linha_gerir, "🗑 Remover selecionada", self._remover_tarefa,
        ).pack(side="left", padx=(8, 0))

        self.lbl_aviso_tarefa = tk.Label(
            wrap, text="", font=(FONTE, 9), fg=COR_FOCO, bg=COR_FUNDO,
        )
        self.lbl_aviso_tarefa.pack(anchor="w")

        self._recarregar_lista_tarefas()

        # ---- Salvar ----
        self._criar_botao(
            wrap, "💾  Salvar configurações", self.salvar_configuracoes,
            cor=COR_INTERVALO, principal=True,
        ).pack(pady=(18, 4))

        self.lbl_aviso_config = tk.Label(
            wrap, text="", font=(FONTE, 9), fg=COR_INTERVALO, bg=COR_FUNDO,
        )
        self.lbl_aviso_config.pack(pady=(0, 16))

    def _frame_rolavel(self, pai):
        """Cria um container com rolagem vertical e devolve o frame interno."""
        canvas = tk.Canvas(pai, bg=COR_FUNDO, highlightthickness=0)
        scroll = ttk.Scrollbar(pai, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COR_FUNDO)

        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        janela = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(janela, width=e.width),
        )
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(24, 0))
        scroll.pack(side="right", fill="y")

        # Rolagem com a roda do mouse só enquanto o ponteiro está sobre a área.
        def _rolar(evento):
            canvas.yview_scroll(int(-evento.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _rolar))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _titulo_secao(self, pai, texto):
        tk.Label(
            pai, text=texto, font=(FONTE, 13, "bold"),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(16, 8))

    def _linha_som(self, pai, rotulo, variavel):
        linha = tk.Frame(pai, bg=COR_FUNDO)
        linha.pack(fill="x", pady=5)
        tk.Label(
            linha, text=rotulo, font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        # Botão de teste do som selecionado.
        self._criar_botao(
            linha, "▶", lambda: sons.tocar(variavel.get(), self.var_volume.get()),
        ).pack(side="right", padx=(6, 0))
        combo = ttk.Combobox(
            linha, textvariable=variavel, values=sons.NOMES_ALERTAS,
            state="readonly", width=14, font=(FONTE, 10),
        )
        combo.pack(side="right")

    def _linha_spin(self, pai, rotulo, variavel, minimo, maximo):
        linha = tk.Frame(pai, bg=COR_FUNDO)
        linha.pack(fill="x", pady=5)
        tk.Label(
            linha, text=rotulo, font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")
        spin = tk.Spinbox(
            linha, from_=minimo, to=maximo, textvariable=variavel,
            width=5, font=(FONTE, 11), justify="center",
            bg=COR_PAINEL, fg=COR_TEXTO, buttonbackground=COR_BOTAO,
            relief="flat", insertbackground=COR_TEXTO,
            highlightthickness=1, highlightbackground=COR_TRILHA,
        )
        spin.pack(side="right")

    def _linha_check(self, pai, rotulo, variavel):
        chk = tk.Checkbutton(
            pai, text=rotulo, variable=variavel,
            font=(FONTE, 10), fg=COR_TEXTO, bg=COR_FUNDO,
            selectcolor=COR_PAINEL, activebackground=COR_FUNDO,
            activeforeground=COR_TEXTO, anchor="w",
            highlightthickness=0, bd=0,
        )
        chk.pack(fill="x", pady=4)

    # ===================================================================== #
    # Lógica do timer
    # ===================================================================== #
    def _duracao_estado(self, estado: str) -> int:
        """Minutos configurados para um estado."""
        if estado == FOCO:
            return self.config["pomodoro_min"]
        if estado == INTERVALO_LONGO:
            return self.config["intervalo_longo_min"]
        return self.config["intervalo_min"]

    def alternar_play_pause(self) -> None:
        if self.rodando:
            self._pausar()
        else:
            self._iniciar()

    def _iniciar(self) -> None:
        # Exige uma tarefa selecionada antes de começar um foco.
        if self.estado == FOCO and not self.var_tarefa.get().strip():
            messagebox.showwarning(
                "Selecione o foco",
                "Escolha no que você vai focar antes de iniciar.\n\n"
                "Se a lista estiver vazia, adicione itens na aba "
                "Configurações › Tarefas de foco.",
            )
            self.combo_tarefa.focus_set()
            return

        self.rodando = True
        self.btn_iniciar.config(text="⏸  Pausar")
        self._atualizar_icone_bandeja()
        self._bloquear_tarefa(True)
        # O ambiente entra com um pequeno atraso para não engolir o alerta
        # de fim de ciclo (o winsound só toca um som por vez).
        self.root.after(1500, self._iniciar_ambiente)
        self._tique()

    def _pausar(self) -> None:
        self.rodando = False
        self.btn_iniciar.config(text="▶  Iniciar")
        self._atualizar_icone_bandeja()
        self._bloquear_tarefa(False)
        sons.parar_ambiente()
        if self._job is not None:
            self.root.after_cancel(self._job)
            self._job = None

    def _ambiente_ligado(self) -> bool:
        """True se há um som ambiente configurado para tocar no foco."""
        return (
            self.config.get("som_ambiente", "Nenhum") != "Nenhum"
            and self.config.get("volume", 80) > 0
        )

    def _iniciar_ambiente(self) -> None:
        """Liga o som ambiente, se configurado e se o foco segue rodando."""
        if self.rodando and self.estado == FOCO and self._ambiente_ligado():
            sons.tocar_ambiente(
                self.config["som_ambiente"], self.config.get("volume", 80),
            )

    def _bloquear_tarefa(self, bloquear: bool) -> None:
        """Trava o combobox durante a contagem (valor fixo)."""
        self.combo_tarefa.config(state="disabled" if bloquear else "readonly")

    def _estilizar_dropdown_tarefa(self) -> None:
        """Enfeita o popdown do combobox de foco: fonte maior, tema escuro,
        itens centralizados e dois tons alternados (zebra) entre as linhas. Roda
        via ``postcommand``, ou seja, é reaplicado toda vez que a lista abre
        (inclusive após editar as tarefas). O listbox interno é acessado pela
        proc padrão do ttk; se a versão do Tk mudar isso, o try/except deixa o
        combobox seguir normal, só sem os enfeites."""
        combo = self.combo_tarefa
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
        except tk.TclError:
            return
        lista = f"{popdown}.f.l"

        def pintar() -> None:
            # after_idle: roda depois de o Tk repovoar o listbox com os valores
            # atuais, garantindo que os índices coloridos batam com os itens.
            try:
                combo.tk.call(
                    lista, "configure",
                    "-font", (FONTE, 12),
                    "-justify", "center",
                    "-background", COR_PAINEL,
                    "-foreground", COR_TEXTO,
                    "-selectbackground", COR_FOCO,
                    "-selectforeground", "#ffffff",
                    "-activestyle", "none",
                    "-borderwidth", 0,
                    "-highlightthickness", 0,
                )
                for i in range(len(combo.cget("values"))):
                    cor = COR_ITEM_ESCURO if i % 2 == 0 else COR_ITEM_CLARO
                    combo.tk.call(
                        lista, "itemconfigure", i,
                        "-background", cor,
                        "-foreground", COR_ITEM_TEXTO,
                    )
            except tk.TclError:
                pass

        self.root.after_idle(pintar)

    def _tique(self) -> None:
        if not self.rodando:
            return
        if self.segundos_restantes <= 0:
            self._concluir_ciclo()
            return
        self._atualizar_visor()
        # Bipe nos últimos 3 segundos antes de finalizar. Com som ambiente
        # ativo no foco, os bipes são pulados: o winsound só toca um som por
        # vez e cada bipe mataria o loop ambiente.
        if (
            self.config.get("som_ao_terminar")
            and self.config.get("bipe_contagem_regressiva")
            and self.segundos_restantes in (1, 2, 3)
            and not (self.estado == FOCO and self._ambiente_ligado())
        ):
            sons.tocar_tique(self.config.get("volume", 80))
        self.segundos_restantes -= 1
        self._job = self.root.after(1000, self._tique)

    def _concluir_ciclo(self) -> None:
        self.rodando = False
        self.btn_iniciar.config(text="▶  Iniciar")

        terminou_foco = self.estado == FOCO
        tarefa = self.var_tarefa.get().strip() or "(sem descrição)"

        # Alerta sonoro de acordo com o ciclo que terminou.
        if self.config.get("som_ao_terminar"):
            nome_som = (
                self.config["som_fim_pomodoro"] if terminou_foco
                else self.config["som_fim_intervalo"]
            )
            sons.tocar(nome_som, self.config.get("volume", 80))

        prorrogacao = self._prorrogacao
        self._prorrogacao = False

        if terminou_foco:
            if prorrogacao:
                # Fim de um "+X min": soma os minutos extras à duração do
                # pomodoro que foi prorrogado (faz parte dele), sem criar um
                # registro parcial isolado nem contar como novo pomodoro.
                db.estender_ultimo_pomodoro(self.segundos_totais // 60, tarefa)
            else:
                # Registra o pomodoro concluído.
                db.registrar_pomodoro(
                    tarefa, self.config["pomodoro_min"],
                    dias_manter=self.config.get("dias_historico", 30),
                )
                self.pomodoros_concluidos_sessao += 1
                self.lbl_sessao.config(
                    text=f"Pomodoros nesta sessão: {self.pomodoros_concluidos_sessao}"
                )
            self._atualizar_aba_historico()
            self._verificar_meta_diaria()
            self._atualizar_aba_jardim()

        proximo = self._proximo_estado()

        # Monta título/mensagem da transição.
        if terminou_foco:
            titulo = "Pomodoro concluído! 🍅"
            if proximo == FOCO:
                msg = f"“{tarefa}” — emendando o próximo foco."
            else:
                nome = "intervalo longo" if proximo == INTERVALO_LONGO else "intervalo"
                msg = f"“{tarefa}” — hora do {nome}."
            cor = COR_FOCO
        else:
            titulo = "Intervalo concluído ✅"
            msg = "De volta ao foco!"
            cor = COR_INTERVALO

        # Notificação no canto (Windows) e/ou aviso grande no centro.
        # No fim de um foco, o aviso central oferece prorrogar por +5 min.
        self._notificar(titulo, msg)
        if self.config.get("aviso_central"):
            self._mostrar_aviso_central(
                titulo, msg, cor,
                ao_prorrogar=self._prorrogar_foco if terminou_foco else None,
            )

        self._preparar_estado(proximo)
        # Inicia o próximo ciclo, a menos que o auto-início esteja desligado.
        if self.config.get("auto_iniciar", True):
            self._iniciar()

    def _prorrogar_foco(self) -> None:
        """Continua focando pelos minutos de prorrogação configurados
        após o fim de um pomodoro. O intervalo que estava por vir
        acontece normalmente depois."""
        self._pausar()  # interrompe o intervalo que possa ter começado
        self._prorrogacao = True
        self.estado = FOCO
        self.segundos_totais = max(1, int(self.config.get("prorrogacao_min", 5))) * 60
        self.segundos_restantes = self.segundos_totais
        self.lbl_estado.config(text="FOCO", fg=COR_FOCO)
        self._definir_cor_anel(COR_FOCO)
        self._atualizar_visor()
        self._iniciar()

    def _verificar_meta_diaria(self) -> None:
        """Avisa (uma vez) quando a meta diária de pomodoros é atingida."""
        meta = int(self.config.get("meta_pomodoros_dia", 0) or 0)
        self._atualizar_rotulo_meta()
        if meta > 0 and db.pomodoros_do_dia() == meta:
            self._notificar(
                "Meta diária atingida! 🎉",
                f"Você completou seus {meta} pomodoros de hoje. Parabéns!",
            )

    def _proximo_estado(self) -> str:
        if self.estado != FOCO:
            return FOCO  # acabou um intervalo -> volta ao foco
        # Acabou um foco.
        if not self.config["usar_intervalos"]:
            return FOCO
        ate_longo = max(1, self.config["pomodoros_ate_intervalo_longo"])
        if self.pomodoros_concluidos_sessao % ate_longo == 0:
            return INTERVALO_LONGO
        return INTERVALO_CURTO

    def _preparar_estado(self, estado: str) -> None:
        self.estado = estado
        self.segundos_totais = self._duracao_estado(estado) * 60
        self.segundos_restantes = self.segundos_totais

        if estado == FOCO:
            cor, rotulo = COR_FOCO, "FOCO"
        elif estado == INTERVALO_LONGO:
            cor, rotulo = COR_INTERVALO, "INTERVALO LONGO"
        else:
            cor, rotulo = COR_INTERVALO, "INTERVALO"

        self.lbl_estado.config(text=rotulo, fg=cor)
        self._definir_cor_anel(cor)
        self._atualizar_icone_bandeja()
        self._atualizar_visor()

    def _definir_cor_anel(self, cor: str) -> None:
        self.canvas.itemconfig(self.arco_progresso, outline=cor)
        self.canvas.itemconfig(self.cap_inicio, fill=cor)
        self.canvas.itemconfig(self.cap_fim, fill=cor)

    def _registrar_foco_parcial(self) -> None:
        """Aproveita o tempo já focado quando um foco é interrompido no meio.

        Só age se houver ao menos 1 minuto decorrido — assim os minutos não se
        perdem. O destino depende do tipo de foco:

          * prorrogação (+X min) interrompida: o tempo faz parte do pomodoro
            que estava sendo estendido, então é SOMADO à duração dele;
          * foco normal abandonado: vira um registro parcial ◐, que soma
            minutos mas não conta como pomodoro completo (meta/streak ignoram)."""
        if self.estado != FOCO:
            return
        decorrido = self.segundos_totais - self.segundos_restantes
        if decorrido < 60:
            return
        tarefa = self.var_tarefa.get().strip() or "(sem descrição)"
        if self._prorrogacao:
            db.estender_ultimo_pomodoro(decorrido // 60, tarefa)
        else:
            db.registrar_pomodoro(
                tarefa, decorrido // 60,
                dias_manter=self.config.get("dias_historico", 30),
                parcial=True,
            )
        self._atualizar_aba_historico()
        self._atualizar_aba_jardim()

    def reiniciar_ciclo(self) -> None:
        """Volta o ciclo atual ao tempo cheio, sem perder o estado."""
        self._pausar()
        self._registrar_foco_parcial()
        self.segundos_restantes = self.segundos_totais
        self._atualizar_visor()

    def pular_ciclo(self) -> None:
        """Pula para o próximo estado, aproveitando o foco parcial se houver."""
        self._pausar()
        self._registrar_foco_parcial()
        self._prorrogacao = False
        self._preparar_estado(self._proximo_estado())

    # ===================================================================== #
    # Atualização visual
    # ===================================================================== #
    def _atualizar_visor(self) -> None:
        minutos, segundos = divmod(max(0, self.segundos_restantes), 60)
        self.canvas.itemconfig(self.txt_tempo, text=f"{minutos:02d}:{segundos:02d}")

        # Rótulo do ciclo central.
        if self.estado != FOCO:
            self.canvas.itemconfig(self.txt_ciclo, text="Respire um pouco")
        elif self._prorrogacao:
            self.canvas.itemconfig(
                self.txt_ciclo,
                text=f"Prorrogação ➕{self.segundos_totais // 60} min",
            )
        else:
            n = self.pomodoros_concluidos_sessao + 1
            self.canvas.itemconfig(self.txt_ciclo, text=f"Pomodoro {n}")

        # Arco proporcional ao tempo decorrido.
        if self.segundos_totais > 0:
            fracao = 1 - (self.segundos_restantes / self.segundos_totais)
        else:
            fracao = 0
        extent = -359.999 * fracao  # sentido horário a partir do topo
        self.canvas.itemconfig(self.arco_progresso, extent=extent)

        # Reposiciona as pontas arredondadas (início fixo no topo, fim
        # acompanhando o progresso).
        if fracao > 0:
            centro = self.tamanho_anel / 2
            meia = 7  # metade da espessura do anel
            for item, ang_graus in (
                (self.cap_inicio, 90.0),
                (self.cap_fim, 90.0 + extent),
            ):
                ang = math.radians(ang_graus)
                x = centro + self.raio_anel * math.cos(ang)
                y = centro - self.raio_anel * math.sin(ang)
                self.canvas.coords(item, x - meia, y - meia, x + meia, y + meia)
                self.canvas.itemconfig(item, state="normal")
        else:
            self.canvas.itemconfig(self.cap_inicio, state="hidden")
            self.canvas.itemconfig(self.cap_fim, state="hidden")

    def _atualizar_aba_historico(self) -> None:
        historico = db.carregar_historico()
        # Lista completa em memória: editar/remover um registro altera esta
        # lista e a regrava por inteiro no arquivo.
        self._historico_completo = historico

        # Dias distintos presentes no histórico (parte AAAA-MM-DD da data),
        # do mais recente para o mais antigo, para alimentar o filtro.
        # O dia atual entra sempre na lista para poder ficar selecionado por
        # padrão mesmo que ainda não haja registros de hoje.
        hoje = date.today().isoformat()
        dias = sorted({reg["data"][:10] for reg in historico} | {hoje}, reverse=True)
        self.combo_filtro_dia.config(values=[self.FILTRO_TODOS] + dias)

        # Se o dia selecionado sumiu (ex.: após limpar dados), volta para "todos".
        dia_sel = self.var_filtro_dia.get()
        if dia_sel != self.FILTRO_TODOS and dia_sel not in dias:
            dia_sel = self.FILTRO_TODOS
            self.var_filtro_dia.set(dia_sel)

        # Tarefas distintas presentes no histórico, em ordem alfabética,
        # para alimentar o filtro por tarefa.
        tarefas = sorted({reg["tarefa"] for reg in historico})
        self.combo_filtro_tarefa.config(
            values=[self.FILTRO_TODAS_TAREFAS] + tarefas,
        )

        # Se a tarefa selecionada sumiu, volta para "todas as tarefas".
        tarefa_sel = self.var_filtro_tarefa.get()
        if tarefa_sel != self.FILTRO_TODAS_TAREFAS and tarefa_sel not in tarefas:
            tarefa_sel = self.FILTRO_TODAS_TAREFAS
            self.var_filtro_tarefa.set(tarefa_sel)

        # Aplica os filtros (dia e tarefa).
        registros = historico
        if dia_sel != self.FILTRO_TODOS:
            registros = [r for r in registros if r["data"][:10] == dia_sel]
        if tarefa_sel != self.FILTRO_TODAS_TAREFAS:
            registros = [r for r in registros if r["tarefa"] == tarefa_sel]
        # Conjunto exibido; é este que o "Exportar CSV" salva.
        self._registros_filtrados = registros

        # Totais recalculados sobre o conjunto filtrado.
        total_min = sum(int(r.get("duracao_min", 0)) for r in registros)
        horas, minutos = divmod(total_min, 60)
        texto_tempo = f"{horas}h {minutos}min" if horas else f"{minutos} min"
        self._definir_valor_cartao(self.cartao_total_foco, texto_tempo)
        # Parciais (focos interrompidos) somam minutos, mas não contam como
        # pomodoro concluído.
        completos = sum(1 for r in registros if not r.get("parcial"))
        self._definir_valor_cartao(self.cartao_qtd, str(completos))

        # Recarrega a tabela (mais recentes no topo), guardando qual registro
        # corresponde a cada linha para as ações de editar/remover.
        for item in self.tabela.get_children():
            self.tabela.delete(item)
        self._registro_por_item = {}
        for reg in reversed(registros):
            parcial = bool(reg.get("parcial"))
            iid = self.tabela.insert(
                "", "end",
                values=(
                    reg["data"], reg["tarefa"],
                    f"{reg['duracao_min']} ◐" if parcial else reg["duracao_min"],
                ),
                tags=("parcial",) if parcial else (),
            )
            self._registro_por_item[iid] = reg

    # ------------------ Edição/remoção de registros ---------------------- #
    def _apos_alterar_historico(self) -> None:
        """Reflete uma alteração do histórico em todas as telas de uma vez:
        tabela/cartões do Histórico, aba Estatísticas e meta da aba Timer."""
        self._atualizar_aba_historico()
        self._atualizar_estatisticas()
        self._atualizar_aba_jardim()
        self._atualizar_rotulo_meta()

    def _registro_selecionado(self) -> dict | None:
        """Registro correspondente à linha selecionada na tabela (ou None)."""
        selecao = self.tabela.selection()
        if not selecao:
            messagebox.showinfo(
                "Registros",
                "Selecione um registro na tabela primeiro.",
                parent=self.root,
            )
            return None
        return self._registro_por_item.get(selecao[0])

    def _remover_registro(self) -> None:
        """Apaga o registro selecionado (com confirmação)."""
        reg = self._registro_selecionado()
        if reg is None:
            return
        if not messagebox.askyesno(
            "Remover registro",
            "Remover este registro do histórico?\n\n"
            f"{reg.get('data', '')}  ·  {reg.get('tarefa', '')}  ·  "
            f"{reg.get('duracao_min', 0)} min\n\n"
            "Esta ação não pode ser desfeita.",
            parent=self.root,
        ):
            return
        try:
            self._historico_completo.remove(reg)
        except ValueError:
            pass  # já não está mais na lista (ex.: histórico recarregado)
        db.salvar_historico(self._historico_completo)
        self._apos_alterar_historico()

    def _adicionar_registro(self) -> None:
        """Janela para incluir manualmente um pomodoro no histórico
        (ex.: um foco feito longe do computador)."""
        win = tk.Toplevel(self.root)
        win.title("Adicionar registro")
        win.configure(bg=COR_FUNDO)
        win.resizable(False, False)
        win.transient(self.root)

        largura, altura = 340, 380
        x = self.root.winfo_rootx() + (self.root.winfo_width() - largura) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - altura) // 3
        win.geometry(f"{largura}x{altura}+{x}+{max(0, y)}")

        interno = tk.Frame(win, bg=COR_FUNDO)
        interno.pack(fill="both", expand=True, padx=20, pady=16)

        def _entrada(pai, variavel, largura_chars):
            return tk.Entry(
                pai, textvariable=variavel, width=largura_chars,
                font=(FONTE, 11), justify="center",
                bg=COR_PAINEL, fg=COR_TEXTO, relief="flat",
                insertbackground=COR_TEXTO,
                highlightthickness=1, highlightbackground=COR_TRILHA,
                highlightcolor=COR_FOCO,
            )

        # Data e hora, já preenchidas com o momento atual.
        agora = datetime.now()
        linha_dt = tk.Frame(interno, bg=COR_FUNDO)
        linha_dt.pack(fill="x")
        col_data = tk.Frame(linha_dt, bg=COR_FUNDO)
        col_data.pack(side="left")
        tk.Label(
            col_data, text="Data (AAAA-MM-DD)", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(0, 2))
        var_data = tk.StringVar(value=agora.strftime("%Y-%m-%d"))
        _entrada(col_data, var_data, 12).pack(anchor="w", ipady=4)
        col_hora = tk.Frame(linha_dt, bg=COR_FUNDO)
        col_hora.pack(side="left", padx=(14, 0))
        tk.Label(
            col_hora, text="Hora (HH:MM)", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(0, 2))
        var_hora = tk.StringVar(value=agora.strftime("%H:%M"))
        _entrada(col_hora, var_hora, 7).pack(anchor="w", ipady=4)

        # Tarefa: mesmas sugestões da janela de edição; começa na tarefa
        # selecionada na aba Timer.
        tk.Label(
            interno, text="Tarefa", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(12, 2))
        sugestoes = sorted(
            set(self.config.get("tarefas", []))
            | {r.get("tarefa", "") for r in self._historico_completo} - {""}
        )
        var_tarefa = tk.StringVar(value=self.var_tarefa.get())
        combo = ttk.Combobox(
            interno, textvariable=var_tarefa, values=sugestoes,
            font=(FONTE, 11),
        )
        combo.pack(fill="x", ipady=4)

        tk.Label(
            interno, text="Duração (min)", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(12, 2))
        var_min = tk.StringVar(value=str(self.config["pomodoro_min"]))
        tk.Spinbox(
            interno, from_=1, to=600, textvariable=var_min,
            width=6, font=(FONTE, 11), justify="center",
            bg=COR_PAINEL, fg=COR_TEXTO, buttonbackground=COR_BOTAO,
            relief="flat", insertbackground=COR_TEXTO,
            highlightthickness=1, highlightbackground=COR_TRILHA,
        ).pack(anchor="w")

        # Parcial: soma minutos, mas não conta como pomodoro completo.
        var_parcial = tk.BooleanVar(value=False)
        tk.Checkbutton(
            interno, text="Registro parcial ◐ (não conta na meta/sequência)",
            variable=var_parcial, font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_FUNDO, selectcolor=COR_PAINEL,
            activebackground=COR_FUNDO, activeforeground=COR_TEXTO,
            anchor="w", highlightthickness=0, bd=0,
        ).pack(fill="x", pady=(10, 0))

        lbl_erro = tk.Label(
            interno, text="", font=(FONTE, 9), fg=COR_FOCO, bg=COR_FUNDO,
            wraplength=largura - 50, justify="left",
        )
        lbl_erro.pack(anchor="w", pady=(8, 0))

        def _salvar():
            try:
                momento = datetime.strptime(
                    f"{var_data.get().strip()} {var_hora.get().strip()}",
                    "%Y-%m-%d %H:%M",
                )
            except ValueError:
                lbl_erro.config(
                    text="Data/hora inválidas. Use os formatos "
                         "AAAA-MM-DD e HH:MM (ex.: 2026-07-04 e 09:30).",
                )
                return
            dias_manter = int(self.config.get("dias_historico", 30) or 0)
            if dias_manter > 0 and momento < datetime.now() - timedelta(days=dias_manter):
                lbl_erro.config(
                    text=f"Data anterior ao limite de {dias_manter} dias do "
                         "histórico: o registro seria apagado automaticamente. "
                         "Ajuste a data ou o limite nas Configurações.",
                )
                return
            tarefa = var_tarefa.get().strip()
            if not tarefa:
                lbl_erro.config(text="Informe o nome da tarefa.")
                return
            try:
                minutos = int(var_min.get())
            except ValueError:
                lbl_erro.config(text="Duração inválida: use um número de minutos.")
                return
            if not (1 <= minutos <= 600):
                lbl_erro.config(text="A duração deve ficar entre 1 e 600 minutos.")
                return

            registro = db.adicionar_registro(
                momento.strftime("%Y-%m-%d %H:%M"), tarefa, minutos,
                parcial=var_parcial.get(),
            )
            win.destroy()
            # Ajusta os filtros para o registro recém-criado ficar visível.
            self.var_filtro_dia.set(registro["data"][:10])
            if self.var_filtro_tarefa.get() not in (
                self.FILTRO_TODAS_TAREFAS, registro["tarefa"],
            ):
                self.var_filtro_tarefa.set(self.FILTRO_TODAS_TAREFAS)
            self._apos_alterar_historico()

        botoes = tk.Frame(interno, bg=COR_FUNDO)
        botoes.pack(pady=(10, 0))
        self._criar_botao(
            botoes, "➕ Adicionar", _salvar, cor=COR_INTERVALO, principal=True,
        ).pack(side="left")
        self._criar_botao(
            botoes, "Cancelar", win.destroy,
        ).pack(side="left", padx=(10, 0))

        win.bind("<Return>", lambda e: _salvar())
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        combo.focus_set()

    def _editar_registro(self) -> None:
        """Janela para alterar a tarefa e a duração do registro selecionado."""
        reg = self._registro_selecionado()
        if reg is None:
            return

        win = tk.Toplevel(self.root)
        win.title("Editar registro")
        win.configure(bg=COR_FUNDO)
        win.resizable(False, False)
        win.transient(self.root)

        largura, altura = 340, 300
        x = self.root.winfo_rootx() + (self.root.winfo_width() - largura) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - altura) // 3
        win.geometry(f"{largura}x{altura}+{x}+{max(0, y)}")

        interno = tk.Frame(win, bg=COR_FUNDO)
        interno.pack(fill="both", expand=True, padx=20, pady=16)

        rotulo_data = reg.get("data", "")
        if reg.get("parcial"):
            rotulo_data += "   ·   parcial ◐"
        tk.Label(
            interno, text=rotulo_data, font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        ).pack(anchor="w")

        # Tarefa: campo livre com sugestões (lista das Configurações +
        # nomes que já aparecem no histórico).
        tk.Label(
            interno, text="Tarefa", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(12, 2))
        sugestoes = sorted(
            set(self.config.get("tarefas", []))
            | {r.get("tarefa", "") for r in self._historico_completo} - {""}
        )
        var_tarefa = tk.StringVar(value=reg.get("tarefa", ""))
        combo = ttk.Combobox(
            interno, textvariable=var_tarefa, values=sugestoes,
            font=(FONTE, 11),
        )
        combo.pack(fill="x", ipady=4)

        tk.Label(
            interno, text="Duração (min)", font=(FONTE, 10),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(anchor="w", pady=(12, 2))
        var_min = tk.StringVar(value=str(reg.get("duracao_min", 0)))
        tk.Spinbox(
            interno, from_=1, to=600, textvariable=var_min,
            width=6, font=(FONTE, 11), justify="center",
            bg=COR_PAINEL, fg=COR_TEXTO, buttonbackground=COR_BOTAO,
            relief="flat", insertbackground=COR_TEXTO,
            highlightthickness=1, highlightbackground=COR_TRILHA,
        ).pack(anchor="w")

        lbl_erro = tk.Label(
            interno, text="", font=(FONTE, 9), fg=COR_FOCO, bg=COR_FUNDO,
        )
        lbl_erro.pack(anchor="w", pady=(8, 0))

        def _salvar():
            tarefa = var_tarefa.get().strip()
            if not tarefa:
                lbl_erro.config(text="Informe o nome da tarefa.")
                return
            try:
                minutos = int(var_min.get())
            except ValueError:
                lbl_erro.config(text="Duração inválida: use um número de minutos.")
                return
            if not (1 <= minutos <= 600):
                lbl_erro.config(text="A duração deve ficar entre 1 e 600 minutos.")
                return
            reg["tarefa"] = tarefa
            reg["duracao_min"] = minutos
            db.salvar_historico(self._historico_completo)
            win.destroy()
            self._apos_alterar_historico()

        botoes = tk.Frame(interno, bg=COR_FUNDO)
        botoes.pack(pady=(10, 0))
        self._criar_botao(
            botoes, "💾 Salvar", _salvar, cor=COR_INTERVALO, principal=True,
        ).pack(side="left")
        self._criar_botao(
            botoes, "Cancelar", win.destroy,
        ).pack(side="left", padx=(10, 0))

        win.bind("<Return>", lambda e: _salvar())
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        combo.focus_set()

    # ===================================================================== #
    # Ações de configuração e dados
    # ===================================================================== #
    # -------------------- Dispositivo de saída de áudio ------------------ #
    def _popular_dispositivos(self) -> None:
        """Busca os dispositivos de saída em segundo plano (a consulta pode
        instalar o suporte e/ou demorar) e preenche o combobox ao terminar."""
        self.combo_dispositivo.config(values=["Carregando…"])
        self.combo_dispositivo.set("Carregando…")
        self.lbl_disp_aviso.config(text="")

        def carregar():
            nomes = sons.listar_dispositivos()
            self.root.after(0, lambda: self._montar_lista_dispositivos(nomes))

        threading.Thread(target=carregar, daemon=True).start()

    def _recarregar_dispositivos(self) -> None:
        """Botão 🔄: re-enumera os dispositivos (após conectar/desconectar um)."""
        self._popular_dispositivos()

    def _montar_lista_dispositivos(self, nomes: list[str]) -> None:
        """Monta o combobox a partir dos nomes encontrados, mantendo a escolha
        atual selecionada (mesmo que o dispositivo esteja desconectado)."""
        self._disp_nomes_cache = list(nomes)
        rotulos = [self.ROTULO_DISP_PADRAO] + list(nomes)
        valores = [""] + list(nomes)
        # O dispositivo salvo pode não estar presente agora (desconectado):
        # mantém-no na lista para não parecer que a escolha se perdeu.
        if self._disp_valor and self._disp_valor not in valores:
            rotulos.append(f"{self._disp_valor}  (desconectado)")
            valores.append(self._disp_valor)
        self._disp_valores = valores
        self.combo_dispositivo.config(values=rotulos)
        try:
            self.combo_dispositivo.current(valores.index(self._disp_valor))
        except ValueError:
            self.combo_dispositivo.current(0)

        if not nomes:
            self.lbl_disp_aviso.config(
                text=("Nenhum dispositivo listado. O suporte para escolher a "
                      "saída pode não estar disponível — o som segue no padrão "
                      "do Windows. Tente 🔄 para atualizar."),
            )
        else:
            self.lbl_disp_aviso.config(
                text="Não vê seu dispositivo? Conecte-o e clique 🔄 para atualizar.",
            )

    def _ao_escolher_dispositivo(self) -> None:
        """Guarda o valor bruto do item escolhido no combobox."""
        idx = self.combo_dispositivo.current()
        if 0 <= idx < len(self._disp_valores):
            self._disp_valor = self._disp_valores[idx]

    def _testar_dispositivo(self) -> None:
        """Aplica o dispositivo escolhido e toca um som de amostra por ele, para
        o usuário conferir a saída antes de salvar."""
        sons.definir_dispositivo(self._disp_valor or None)
        sons.tocar(self.var_som_pomodoro.get(), self.var_volume.get())

    def _valores_config_atuais(self) -> dict:
        """Lê as variáveis da aba Configurações e devolve o dicionário
        correspondente. Pode lançar tk.TclError se algum campo estiver vazio."""
        return {
            "pomodoro_min": int(self.var_pomodoro.get()),
            "intervalo_min": int(self.var_intervalo.get()),
            "intervalo_longo_min": int(self.var_intervalo_longo.get()),
            "pomodoros_ate_intervalo_longo": int(self.var_ate_longo.get()),
            "usar_intervalos": bool(self.var_usar_intervalos.get()),
            "som_ao_terminar": bool(self.var_som.get()),
            "volume": int(self.var_volume.get()),
            "som_fim_pomodoro": self.var_som_pomodoro.get(),
            "som_fim_intervalo": self.var_som_intervalo.get(),
            "bipe_contagem_regressiva": bool(self.var_bipe.get()),
            "notificacao_windows": bool(self.var_notificacao.get()),
            "aviso_central": bool(self.var_aviso_central.get()),
            "dias_historico": int(self.var_dias_historico.get() or 30),
            "auto_iniciar": bool(self.var_auto_iniciar.get()),
            "prorrogacao_min": int(self.var_prorrogacao_min.get()),
            "som_ambiente": self.var_som_ambiente.get(),
            "meta_pomodoros_dia": int(self.var_meta.get()),
            "dispositivo_audio": self._disp_valor,
        }

    def _config_tem_alteracoes(self) -> bool:
        """True se as configurações na tela diferem das já salvas."""
        try:
            atuais = self._valores_config_atuais()
        except tk.TclError:
            # Campo em branco/ inválido -> trata como alteração pendente.
            return True
        return any(self.config.get(chave) != valor for chave, valor in atuais.items())

    def salvar_configuracoes(self) -> None:
        self.config.update(self._valores_config_atuais())
        db.salvar_config(self.config)

        # Aplica de imediato a saída de áudio escolhida.
        dispositivo = self.config.get("dispositivo_audio", "")
        sons.definir_dispositivo(dispositivo or None)
        if dispositivo:
            sons.garantir_async()

        # Aplica imediatamente o novo limite de retenção do histórico.
        db.podar_historico(self.config["dias_historico"])
        self._atualizar_aba_historico()
        self._atualizar_aba_jardim()
        self._atualizar_rotulo_meta()

        # Se o timer estiver parado, aplica o novo tempo ao ciclo atual.
        if not self.rodando:
            self.segundos_totais = self._duracao_estado(self.estado) * 60
            self.segundos_restantes = self.segundos_totais
            self._atualizar_visor()

        self.lbl_aviso_config.config(text="✓ Configurações salvas!")
        self.root.after(2500, lambda: self.lbl_aviso_config.config(text=""))

    def _reverter_config(self) -> None:
        """Restaura as variáveis da aba com os valores atualmente salvos."""
        self.var_pomodoro.set(self.config["pomodoro_min"])
        self.var_intervalo.set(self.config["intervalo_min"])
        self.var_intervalo_longo.set(self.config["intervalo_longo_min"])
        self.var_ate_longo.set(self.config["pomodoros_ate_intervalo_longo"])
        self.var_usar_intervalos.set(self.config["usar_intervalos"])
        self.var_som.set(self.config["som_ao_terminar"])
        self.var_volume.set(self.config["volume"])
        self.var_som_pomodoro.set(self.config["som_fim_pomodoro"])
        self.var_som_intervalo.set(self.config["som_fim_intervalo"])
        self.var_bipe.set(self.config["bipe_contagem_regressiva"])
        self.var_notificacao.set(self.config["notificacao_windows"])
        self.var_aviso_central.set(self.config["aviso_central"])
        self.var_dias_historico.set(str(self.config["dias_historico"]))
        self.var_auto_iniciar.set(self.config["auto_iniciar"])
        self.var_prorrogacao_min.set(self.config["prorrogacao_min"])
        self.var_som_ambiente.set(self.config["som_ambiente"])
        self.var_meta.set(self.config["meta_pomodoros_dia"])
        # Dispositivo de saída: volta ao valor salvo e reaplica na reprodução.
        self._disp_valor = self.config.get("dispositivo_audio", "")
        sons.definir_dispositivo(self._disp_valor or None)
        self._montar_lista_dispositivos(self._disp_nomes_cache)

    def _tratar_config_pendente(self) -> bool:
        """Se houver alterações não salvas na aba Configurações, pergunta o
        que fazer. Retorna False se o usuário escolher Cancelar (para abortar
        a troca de aba / o fechamento em curso)."""
        if not self._config_tem_alteracoes():
            return True
        resposta = messagebox.askyesnocancel(
            "Configurações não salvas",
            "Você alterou as configurações mas ainda não salvou.\n\n"
            "Deseja salvar as alterações?",
        )
        if resposta is None:      # Cancelar -> permanece onde está
            return False
        if resposta:              # Sim -> salva
            self.salvar_configuracoes()
        else:                     # Não -> descarta e volta aos valores salvos
            self._reverter_config()
        return True

    def _ao_trocar_aba(self, evento=None) -> None:
        """Ao sair da aba de Configurações, avisa se houver algo não salvo."""
        atual = self.abas.index(self.abas.select())
        anterior = self._aba_atual
        self._aba_atual = atual
        if anterior == self._idx_config and atual != self._idx_config:
            if not self._tratar_config_pendente():
                # Cancelou -> traz de volta para a aba de Configurações.
                self._aba_atual = self._idx_config
                self.abas.select(self._idx_config)
                return
        # Estatísticas e Jardim sempre recalculados ao entrar na aba.
        if atual == self._idx_stats:
            self._atualizar_estatisticas()
        elif atual == self._idx_jardim:
            self._atualizar_aba_jardim()

    # --------------------- Lista de tarefas (combobox) ------------------- #
    def _recarregar_lista_tarefas(self) -> None:
        """Reflete a lista salva na Listbox das Configurações."""
        self.lista_tarefas.delete(0, tk.END)
        for t in self.config.get("tarefas", []):
            self.lista_tarefas.insert(tk.END, t)

    def _atualizar_combo_tarefas(self) -> None:
        """Atualiza os itens do combobox da aba Timer."""
        tarefas = self.config.get("tarefas", [])
        self.combo_tarefa.config(values=tarefas)
        if tarefas:
            if self.var_tarefa.get() not in tarefas:
                self.combo_tarefa.current(0)
        else:
            self.var_tarefa.set("")
        self._salvar_tarefa_selecionada()

    def _salvar_tarefa_selecionada(self) -> None:
        """Persiste a tarefa atual para restaurá-la ao reabrir o app."""
        self.config["tarefa_selecionada"] = self.var_tarefa.get()
        db.salvar_config(self.config)

    def _avisar_tarefa(self, texto: str) -> None:
        self.lbl_aviso_tarefa.config(text=texto)
        self.root.after(2500, lambda: self.lbl_aviso_tarefa.config(text=""))

    def _adicionar_tarefa(self) -> None:
        nova = self.entrada_nova_tarefa.get().strip()
        if not nova:
            return
        tarefas = self.config.setdefault("tarefas", [])
        if nova in tarefas:
            self._avisar_tarefa("Esse item já está na lista.")
            return
        tarefas.append(nova)
        db.salvar_config(self.config)  # persiste de imediato
        self.entrada_nova_tarefa.delete(0, tk.END)
        self._recarregar_lista_tarefas()
        self._atualizar_combo_tarefas()
        self._avisar_tarefa(f"✓ “{nova}” adicionado.")

    def _renomear_tarefa(self) -> None:
        """Renomeia a tarefa selecionada, inclusive nos registros antigos."""
        selecao = self.lista_tarefas.curselection()
        if not selecao:
            self._avisar_tarefa("Selecione um item na lista para renomear.")
            return
        idx = selecao[0]
        tarefas = self.config.get("tarefas", [])
        if not (0 <= idx < len(tarefas)):
            return
        antigo = tarefas[idx]
        novo = simpledialog.askstring(
            "Renomear tarefa", f"Novo nome para “{antigo}”:",
            initialvalue=antigo, parent=self.root,
        )
        if novo is None:
            return
        novo = novo.strip()
        if not novo or novo == antigo:
            return
        if novo in tarefas:
            self._avisar_tarefa("Já existe um item com esse nome.")
            return

        tarefas[idx] = novo
        if self.config.get("tarefa_selecionada") == antigo:
            self.config["tarefa_selecionada"] = novo
        if self.var_tarefa.get() == antigo:
            self.var_tarefa.set(novo)
        db.salvar_config(self.config)
        alterados = db.renomear_tarefa_historico(antigo, novo)

        self._recarregar_lista_tarefas()
        self._atualizar_combo_tarefas()
        self._atualizar_aba_historico()
        extra = f" ({alterados} registro(s) atualizados)" if alterados else ""
        self._avisar_tarefa(f"✓ “{antigo}” → “{novo}”{extra}.")

    def _remover_tarefa(self) -> None:
        selecao = self.lista_tarefas.curselection()
        if not selecao:
            self._avisar_tarefa("Selecione um item na lista para remover.")
            return
        idx = selecao[0]
        tarefas = self.config.get("tarefas", [])
        if 0 <= idx < len(tarefas):
            removido = tarefas.pop(idx)
            db.salvar_config(self.config)  # persiste de imediato
            self._recarregar_lista_tarefas()
            self._atualizar_combo_tarefas()
            self._avisar_tarefa(f"✓ “{removido}” removido.")

    def exportar_csv(self) -> None:
        """Salva em CSV os registros atualmente exibidos (com os filtros)."""
        registros = getattr(self, "_registros_filtrados", [])
        if not registros:
            messagebox.showinfo(
                "Exportar CSV",
                "Não há registros para exportar com os filtros atuais.",
            )
            return
        caminho = filedialog.asksaveasfilename(
            title="Exportar histórico",
            defaultextension=".csv",
            filetypes=[("Planilha CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            initialfile=f"foco_pomodoro_{date.today().isoformat()}.csv",
        )
        if not caminho:
            return
        try:
            # utf-8-sig + ponto e vírgula: abre certinho no Excel brasileiro.
            with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
                escritor = csv.writer(f, delimiter=";")
                escritor.writerow(["Data", "Tarefa", "Minutos", "Parcial"])
                for r in registros:
                    escritor.writerow([
                        r.get("data", ""), r.get("tarefa", ""),
                        r.get("duracao_min", 0),
                        "sim" if r.get("parcial") else "não",
                    ])
        except OSError as erro:
            messagebox.showerror(
                "Exportar CSV", f"Não foi possível salvar o arquivo:\n{erro}",
            )
            return
        messagebox.showinfo(
            "Exportar CSV",
            f"{len(registros)} registro(s) exportado(s) para:\n{caminho}",
        )

    def limpar_dados(self) -> None:
        if messagebox.askyesno(
            "Limpar dados",
            "Isso apaga TODO o histórico de pomodoros. Esta ação não "
            "pode ser desfeita.\n\nDeseja continuar?",
        ):
            db.limpar_historico()
            self.pomodoros_concluidos_sessao = 0
            self.lbl_sessao.config(text="Pomodoros nesta sessão: 0")
            self._atualizar_aba_historico()
            self._atualizar_estatisticas()
            self._atualizar_aba_jardim()

    # ===================================================================== #
    def _notificar(self, titulo: str, mensagem: str) -> None:
        if self.config.get("notificacao_windows"):
            notificacao.notificar(titulo, mensagem)

    def _mostrar_aviso_central(
        self, titulo: str, mensagem: str, cor: str, ao_prorrogar=None,
    ) -> None:
        """Janela grande, centralizada, sempre no topo, fixa até o usuário fechar.

        Se `ao_prorrogar` for passado (fim de pomodoro), mostra também um
        botão para continuar focando por mais 5 minutos."""
        # Evita acumular várias janelas: fecha a anterior, se houver.
        anterior = getattr(self, "_janela_aviso", None)
        if anterior is not None:
            try:
                anterior.destroy()
            except tk.TclError:
                pass

        win = tk.Toplevel(self.root)
        self._janela_aviso = win
        win.title("Foco Pomodoro")
        win.configure(bg=COR_FUNDO)
        win.resizable(False, False)
        try:
            win.iconbitmap(default=ICONE_FOCO)
        except tk.TclError:
            pass

        largura, altura = 560, 340
        x = (win.winfo_screenwidth() - largura) // 2
        y = (win.winfo_screenheight() - altura) // 2
        win.geometry(f"{largura}x{altura}+{x}+{y}")

        # Borda colorida sutil em volta do conteúdo.
        moldura = tk.Frame(win, bg=cor)
        moldura.pack(fill="both", expand=True, padx=4, pady=4)
        interno = tk.Frame(moldura, bg=COR_FUNDO)
        interno.pack(fill="both", expand=True, padx=3, pady=3)

        tk.Label(
            interno, text=titulo, font=(FONTE, 26, "bold"),
            fg=cor, bg=COR_FUNDO, wraplength=largura - 60,
        ).pack(pady=(46, 14))
        tk.Label(
            interno, text=mensagem, font=(FONTE, 15),
            fg=COR_TEXTO, bg=COR_FUNDO, wraplength=largura - 80,
        ).pack(pady=(0, 30))

        botoes = tk.Frame(interno, bg=COR_FUNDO)
        botoes.pack()
        self._criar_botao(
            botoes, "Fechar", win.destroy, cor=cor, principal=True,
        ).pack(side="left")
        if ao_prorrogar is not None:
            def _prorrogar():
                win.destroy()
                ao_prorrogar()
            minutos = max(1, int(self.config.get("prorrogacao_min", 5)))
            self._criar_botao(
                botoes, f"➕ {minutos} min de foco", _prorrogar,
            ).pack(side="left", padx=(10, 0))

        # Força ficar acima de todas as aplicações.
        win.attributes("-topmost", True)
        win.lift()
        try:
            win.focus_force()
        except tk.TclError:
            pass
        # Pisca o "topmost" para reforçar a vinda à frente em alguns sistemas.
        win.after(50, lambda: (win.lift(), win.attributes("-topmost", True)))


def _definir_identidade_windows() -> None:
    """Dá ao processo uma identidade própria na barra de tarefas do Windows.

    Sem isso, um app aberto via pythonw.exe herda a identidade (e o ícone) do
    atalho/pythonw, e as trocas de ícone feitas na janela não aparecem no botão
    da barra de tarefas. Com um AppUserModelID próprio, o ícone da janela — e as
    trocas conforme o estado — passam a valer no botão da barra."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "JuanCleber.FocoPomodoro.Timer"
        )
    except Exception:
        pass


def main() -> None:
    # Precisa vir antes de qualquer janela para valer na barra de tarefas.
    _definir_identidade_windows()

    root = tk.Tk()
    app = FocoPomodoro(root)

    # Evita fechar a janela no meio de um pomodoro sem avisar (mesma lógica
    # usada pelo item "Sair" do menu da bandeja).
    root.protocol("WM_DELETE_WINDOW", app.encerrar)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
