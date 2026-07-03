"""
Foco Pomodoro — um timer Pomodoro visual para estudos e trabalho.

Recursos:
  * Tempos de foco e de intervalo configuráveis.
  * Opção de desligar os intervalos (um pomodoro após o outro).
  * Campo de descrição preenchido antes de iniciar (estudos, trabalho...).
  * Histórico persistente em JSON com tempo total de foco.
  * Botão para limpar os dados quando quiser.

Interface feita com tkinter (já incluído no Python). Tema escuro com um
anel circular de progresso desenhado em um Canvas.
"""

from __future__ import annotations

import sys
from datetime import date
import tkinter as tk
from tkinter import messagebox, ttk

import armazenamento as db
import notificacao
import sons


# --------------------------------------------------------------------------- #
# Paleta de cores (tema escuro "tomate")
# --------------------------------------------------------------------------- #
COR_FUNDO = "#1e2030"
COR_PAINEL = "#282b3d"
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

FONTE = "Segoe UI"

# Estados possíveis do ciclo.
FOCO = "foco"
INTERVALO_CURTO = "intervalo_curto"
INTERVALO_LONGO = "intervalo_longo"


class FocoPomodoro:
    FILTRO_TODOS = "Todos os dias"
    FILTRO_TODAS_TAREFAS = "Todas as tarefas"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = db.carregar_config()

        # Ao abrir, já descarta registros de histórico além do limite salvo.
        db.podar_historico(self.config["dias_historico"])

        # Estado do timer ------------------------------------------------- #
        self.estado = FOCO
        self.rodando = False
        self.segundos_restantes = self.config["pomodoro_min"] * 60
        self.segundos_totais = self.segundos_restantes
        self.pomodoros_concluidos_sessao = 0
        self._job = None  # id do agendamento .after()

        self._montar_janela()
        self._montar_interface()
        self._atualizar_visor()
        self._atualizar_aba_historico()

    # ===================================================================== #
    # Construção da janela e da interface
    # ===================================================================== #
    def _montar_janela(self) -> None:
        self.root.title("Foco Pomodoro")
        self.root.configure(bg=COR_FUNDO)

        # Tamanho fixo, centralizado na tela e sem permitir maximizar.
        largura, altura = 460, 660
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
            padding=(18, 8),
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

    def _montar_interface(self) -> None:
        self.abas = ttk.Notebook(self.root)
        self.abas.pack(fill="both", expand=True, padx=10, pady=10)

        self.aba_timer = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_historico = tk.Frame(self.abas, bg=COR_FUNDO)
        self.aba_config = tk.Frame(self.abas, bg=COR_FUNDO)

        self.abas.add(self.aba_timer, text="Timer")
        self.abas.add(self.aba_historico, text="Histórico")
        self.abas.add(self.aba_config, text="Configurações")

        self._montar_aba_timer()
        self._montar_aba_historico()
        self._montar_aba_config()

        # Aviso de configurações não salvas ao sair da aba Configurações.
        self._idx_config = self.abas.index(self.aba_config)
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
            bloco, text="No que você vai focar?",
            font=(FONTE, 10), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        ).pack(anchor="w")
        # Combobox: itens vêm da lista salva em config.json e são gerenciados
        # na aba Configurações. "readonly" = só seleciona, não digita.
        self.var_tarefa = tk.StringVar()
        self.combo_tarefa = ttk.Combobox(
            bloco, textvariable=self.var_tarefa,
            values=self.config.get("tarefas", []),
            state="readonly", font=(FONTE, 12),
        )
        self.combo_tarefa.pack(fill="x", ipady=6, pady=(4, 0))
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
        ).grid(row=0, column=1, padx=5)

        self._criar_botao(
            botoes, "⏭ Pular", self.pular_ciclo,
        ).grid(row=0, column=2, padx=5)

        self.lbl_sessao = tk.Label(
            f, text="Pomodoros nesta sessão: 0",
            font=(FONTE, 10), fg=COR_TEXTO_FRACO, bg=COR_FUNDO,
        )
        self.lbl_sessao.pack(pady=(2, 10))

    def _criar_botao(self, pai, texto, comando, cor=None, principal=False):
        botao = tk.Button(
            pai, text=texto, command=comando,
            font=(FONTE, 11, "bold" if principal else "normal"),
            fg=COR_FUNDO if principal else COR_TEXTO,
            bg=cor or COR_BOTAO,
            activebackground=cor or COR_BOTAO_ATIVO,
            activeforeground=COR_FUNDO if principal else COR_TEXTO,
            relief="flat", bd=0, padx=16, pady=10, cursor="hand2",
        )
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

        # Cabeçalho "Registros".
        cab = tk.Frame(f, bg=COR_FUNDO)
        cab.pack(fill="x", padx=20, pady=(8, 4))
        tk.Label(
            cab, text="Registros", font=(FONTE, 12, "bold"),
            fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(side="left")

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

        scroll = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=scroll.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._criar_botao(
            f, "🗑  Limpar todos os dados", self.limpar_dados,
        ).pack(pady=12)

    def _criar_cartao(self, pai, titulo, valor):
        cartao = tk.Frame(pai, bg=COR_PAINEL)
        tk.Label(
            cartao, text=titulo, font=(FONTE, 9),
            fg=COR_TEXTO_FRACO, bg=COR_PAINEL,
        ).pack(anchor="w", padx=14, pady=(12, 0))
        lbl_valor = tk.Label(
            cartao, text=valor, font=(FONTE, 20, "bold"),
            fg=COR_FOCO, bg=COR_PAINEL,
        )
        lbl_valor.pack(anchor="w", padx=14, pady=(0, 12))
        cartao.lbl_valor = lbl_valor  # guarda referência para atualizar
        return cartao

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

        # ---- Tempos ----
        self._titulo_secao(wrap, "⏱  Tempos")
        self._linha_spin(wrap, "Duração do foco (min)", self.var_pomodoro, 1, 180)
        self._linha_spin(wrap, "Intervalo curto (min)", self.var_intervalo, 1, 60)
        self._linha_spin(wrap, "Intervalo longo (min)", self.var_intervalo_longo, 1, 90)
        self._linha_spin(wrap, "Pomodoros até intervalo longo", self.var_ate_longo, 1, 12)
        self._linha_check(
            wrap, "Usar intervalos (desmarque p/ pomodoros seguidos)",
            self.var_usar_intervalos,
        )

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

        self._criar_botao(
            wrap, "🗑 Remover selecionada", self._remover_tarefa,
        ).pack(anchor="w", pady=(2, 0))

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
        self._bloquear_tarefa(True)
        self._tique()

    def _pausar(self) -> None:
        self.rodando = False
        self.btn_iniciar.config(text="▶  Iniciar")
        self._bloquear_tarefa(False)
        if self._job is not None:
            self.root.after_cancel(self._job)
            self._job = None

    def _bloquear_tarefa(self, bloquear: bool) -> None:
        """Trava o combobox durante a contagem (valor fixo)."""
        self.combo_tarefa.config(state="disabled" if bloquear else "readonly")

    def _tique(self) -> None:
        if not self.rodando:
            return
        if self.segundos_restantes <= 0:
            self._concluir_ciclo()
            return
        self._atualizar_visor()
        # Bipe nos últimos 3 segundos antes de finalizar.
        if (
            self.config.get("som_ao_terminar")
            and self.config.get("bipe_contagem_regressiva")
            and self.segundos_restantes in (1, 2, 3)
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

        if terminou_foco:
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
        self._notificar(titulo, msg)
        if self.config.get("aviso_central"):
            self._mostrar_aviso_central(titulo, msg, cor)

        self._preparar_estado(proximo)
        # Inicia automaticamente o próximo ciclo (a tarefa já está preenchida).
        self._iniciar()

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
        self.canvas.itemconfig(self.arco_progresso, outline=cor)
        self._atualizar_visor()

    def reiniciar_ciclo(self) -> None:
        """Volta o ciclo atual ao tempo cheio, sem perder o estado."""
        self._pausar()
        self.segundos_restantes = self.segundos_totais
        self._atualizar_visor()

    def pular_ciclo(self) -> None:
        """Pula direto para o próximo estado, sem registrar foco incompleto."""
        self._pausar()
        self._preparar_estado(self._proximo_estado())

    # ===================================================================== #
    # Atualização visual
    # ===================================================================== #
    def _atualizar_visor(self) -> None:
        minutos, segundos = divmod(max(0, self.segundos_restantes), 60)
        self.canvas.itemconfig(self.txt_tempo, text=f"{minutos:02d}:{segundos:02d}")

        # Rótulo do ciclo central.
        if self.estado == FOCO:
            n = self.pomodoros_concluidos_sessao + 1
            self.canvas.itemconfig(self.txt_ciclo, text=f"Pomodoro {n}")
        else:
            self.canvas.itemconfig(self.txt_ciclo, text="Respire um pouco")

        # Arco proporcional ao tempo decorrido.
        if self.segundos_totais > 0:
            fracao = 1 - (self.segundos_restantes / self.segundos_totais)
        else:
            fracao = 0
        extent = -359.999 * fracao  # sentido horário a partir do topo
        self.canvas.itemconfig(self.arco_progresso, extent=extent)

    def _atualizar_aba_historico(self) -> None:
        historico = db.carregar_historico()

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

        # Totais recalculados sobre o conjunto filtrado.
        total_min = sum(int(r.get("duracao_min", 0)) for r in registros)
        horas, minutos = divmod(total_min, 60)
        texto_tempo = f"{horas}h {minutos}min" if horas else f"{minutos} min"
        self.cartao_total_foco.lbl_valor.config(text=texto_tempo)
        self.cartao_qtd.lbl_valor.config(text=str(len(registros)))

        # Recarrega a tabela (mais recentes no topo).
        for item in self.tabela.get_children():
            self.tabela.delete(item)
        for reg in reversed(registros):
            self.tabela.insert(
                "", "end",
                values=(reg["data"], reg["tarefa"], reg["duracao_min"]),
            )

    # ===================================================================== #
    # Ações de configuração e dados
    # ===================================================================== #
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

        # Aplica imediatamente o novo limite de retenção do histórico.
        db.podar_historico(self.config["dias_historico"])
        self._atualizar_aba_historico()

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

    # ===================================================================== #
    def _notificar(self, titulo: str, mensagem: str) -> None:
        if self.config.get("notificacao_windows"):
            notificacao.notificar(titulo, mensagem)

    def _mostrar_aviso_central(self, titulo: str, mensagem: str, cor: str) -> None:
        """Janela grande, centralizada, sempre no topo, fixa até o usuário fechar."""
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
            win.iconbitmap(default="foco.ico")
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
        self._criar_botao(
            interno, "Fechar", win.destroy, cor=cor, principal=True,
        ).pack()

        # Força ficar acima de todas as aplicações.
        win.attributes("-topmost", True)
        win.lift()
        try:
            win.focus_force()
        except tk.TclError:
            pass
        # Pisca o "topmost" para reforçar a vinda à frente em alguns sistemas.
        win.after(50, lambda: (win.lift(), win.attributes("-topmost", True)))


def main() -> None:
    root = tk.Tk()
    app = FocoPomodoro(root)

    # Evita fechar a janela no meio de um pomodoro sem avisar.
    def ao_fechar():
        # Avisa se há configurações alteradas e ainda não salvas.
        if not app._tratar_config_pendente():
            return
        if app.rodando and not messagebox.askyesno(
            "Sair", "O timer está rodando. Deseja realmente sair?"
        ):
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", ao_fechar)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
