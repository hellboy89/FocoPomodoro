"""
Camada de persistência do Foco Pomodoro.

Tudo é salvo em arquivos JSON na mesma pasta da aplicação, de forma que
os dados sobrevivem ao fechar e abrir o programa. São dois arquivos:

    config.json     -> preferências (tempos, uso de intervalos, etc.)
    historico.json  -> registro de pomodoros concluídos

Se os arquivos não existirem, são criados com valores padrão.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

# Pasta onde este arquivo está -> garante que os JSON fiquem junto do app,
# independente de onde o programa for executado.
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG = os.path.join(PASTA, "config.json")
ARQUIVO_HISTORICO = os.path.join(PASTA, "historico.json")

CONFIG_PADRAO = {
    "pomodoro_min": 25,
    "intervalo_min": 5,
    "intervalo_longo_min": 15,
    "pomodoros_ate_intervalo_longo": 4,
    "usar_intervalos": True,
    "som_ao_terminar": True,
    "volume": 80,
    "som_fim_pomodoro": "Sino",
    "som_fim_intervalo": "Bipe duplo",
    "bipe_contagem_regressiva": True,
    "notificacao_windows": True,
    "aviso_central": True,
    # Inicia o próximo ciclo automaticamente ao terminar o atual.
    "auto_iniciar": True,
    # Minutos extras do botão "prorrogar foco" do aviso de fim de pomodoro.
    "prorrogacao_min": 5,
    # Som contínuo durante o foco ("Nenhum" desliga).
    "som_ambiente": "Nenhum",
    # Dispositivo de saída fixo para TODO o som do app, pelo nome que aparece
    # no painel de Som do Windows › Reprodução ("" = segue o padrão do Windows).
    "dispositivo_audio": "",
    # Meta de pomodoros por dia (0 = sem meta).
    "meta_pomodoros_dia": 0,
    # Por quantos dias manter o histórico. Registros mais antigos que isso
    # são descartados automaticamente para não inchar o JSON.
    "dias_historico": 30,
    # Itens que aparecem no combobox "No que você vai focar?" da aba Timer.
    # A lista é livre: o usuário adiciona/remove quantos quiser nas Configurações.
    "tarefas": ["Estudos", "Trabalho", "Leitura"],
    # Último item selecionado no combobox; restaurado ao reabrir o app.
    "tarefa_selecionada": "",
}


# --------------------------------------------------------------------------- #
# Funções internas auxiliares
# --------------------------------------------------------------------------- #
def _ler_json(caminho: str, padrao):
    """Lê um JSON; em caso de erro/ausência devolve o padrão fornecido."""
    if not os.path.exists(caminho):
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Arquivo corrompido ou ilegível: não derruba o app.
        return padrao


def _gravar_json(caminho: str, dados) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
def carregar_config() -> dict:
    """Devolve a config salva, completando chaves ausentes com o padrão."""
    config = dict(CONFIG_PADRAO)
    config["tarefas"] = list(CONFIG_PADRAO["tarefas"])  # cópia própria da lista
    salvo = _ler_json(ARQUIVO_CONFIG, {})
    if isinstance(salvo, dict):
        config.update({k: salvo[k] for k in salvo if k in CONFIG_PADRAO})
    # Garante que "tarefas" seja sempre uma lista de textos.
    if not isinstance(config.get("tarefas"), list):
        config["tarefas"] = list(CONFIG_PADRAO["tarefas"])
    else:
        config["tarefas"] = [str(t) for t in config["tarefas"]]
    return config


def salvar_config(config: dict) -> None:
    _gravar_json(ARQUIVO_CONFIG, config)


# --------------------------------------------------------------------------- #
# Histórico de pomodoros
# --------------------------------------------------------------------------- #
def carregar_historico() -> list[dict]:
    """Lista de registros, do mais antigo ao mais recente."""
    dados = _ler_json(ARQUIVO_HISTORICO, {"pomodoros": []})
    if isinstance(dados, dict):
        registros = dados.get("pomodoros", [])
        return registros if isinstance(registros, list) else []
    return []


def _data_registro(registro: dict) -> datetime | None:
    """Extrai a data de um registro; None se estiver ausente/ inválida."""
    texto = str(registro.get("data", "")).strip()
    for formato in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def podar_historico(dias: int) -> list[dict]:
    """Remove registros mais antigos que `dias` dias e regrava o arquivo.

    Devolve a lista já podada. Registros sem data válida são mantidos
    (não dá para saber se são antigos)."""
    historico = carregar_historico()
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        return historico
    if dias <= 0:
        return historico

    limite = datetime.now() - timedelta(days=dias)
    podado = [
        r for r in historico
        if (_data_registro(r) is None) or (_data_registro(r) >= limite)
    ]
    if len(podado) != len(historico):
        _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": podado})
    return podado


def registrar_pomodoro(
    tarefa: str, duracao_min: int, dias_manter: int = 0, parcial: bool = False,
) -> dict:
    """Acrescenta um pomodoro concluído ao histórico e o devolve.

    `parcial=True` marca um foco interrompido antes do fim (o tempo já
    focado é aproveitado, mas não conta como pomodoro completo).
    Se `dias_manter` > 0, poda registros antigos após gravar."""
    historico = carregar_historico()
    registro = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tarefa": tarefa.strip() or "(sem descrição)",
        "duracao_min": int(duracao_min),
    }
    if parcial:
        registro["parcial"] = True
    historico.append(registro)
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})
    if dias_manter and dias_manter > 0:
        podar_historico(dias_manter)
    return registro


def estender_ultimo_pomodoro(
    minutos_extra: int, tarefa: str | None = None,
) -> dict | None:
    """Soma minutos ao pomodoro COMPLETO mais recente e regrava o arquivo.

    Usado na prorrogação do foco (+X min): o tempo extra faz parte do mesmo
    pomodoro que foi estendido, então é somado à sua duração em vez de virar
    um registro parcial separado (que apareceria como um foco quebrado).

    Se `tarefa` for informada, procura o completo mais recente dessa tarefa;
    não achando (ou se None), usa o completo mais recente de qualquer tarefa.
    Devolve o registro atualizado, ou None se não houver pomodoro completo
    (nem minutos válidos a somar)."""
    try:
        minutos_extra = int(minutos_extra)
    except (TypeError, ValueError):
        return None
    if minutos_extra <= 0:
        return None

    historico = carregar_historico()
    alvo = None
    if tarefa is not None:
        for reg in reversed(historico):
            if not reg.get("parcial") and reg.get("tarefa") == tarefa:
                alvo = reg
                break
    if alvo is None:
        for reg in reversed(historico):
            if not reg.get("parcial"):
                alvo = reg
                break
    if alvo is None:
        return None

    alvo["duracao_min"] = int(alvo.get("duracao_min", 0)) + minutos_extra
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})
    return alvo


def adicionar_registro(
    data_texto: str, tarefa: str, duracao_min: int, parcial: bool = False,
) -> dict:
    """Insere um registro criado manualmente, mantendo a ordem cronológica.

    Diferente de `registrar_pomodoro` (sempre "agora", no fim da lista),
    aqui a data vem do usuário e o registro entra na posição certa para a
    listagem do histórico continuar em ordem."""
    historico = carregar_historico()
    registro = {
        "data": data_texto,
        "tarefa": tarefa.strip() or "(sem descrição)",
        "duracao_min": int(duracao_min),
    }
    if parcial:
        registro["parcial"] = True

    nova_data = _data_registro(registro)
    posicao = len(historico)
    if nova_data is not None:
        for i, reg in enumerate(historico):
            data = _data_registro(reg)
            if data is not None and data > nova_data:
                posicao = i
                break
    historico.insert(posicao, registro)
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})
    return registro


def salvar_historico(historico: list[dict]) -> None:
    """Regrava o arquivo de histórico com a lista fornecida.

    Usado pela aba Histórico ao editar ou remover um registro específico."""
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})


def limpar_historico() -> None:
    """Apaga todos os registros (mantém o arquivo, vazio)."""
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": []})


def resumo_historico() -> dict:
    """Totais úteis para exibir: quantidade e minutos somados."""
    historico = carregar_historico()
    total_min = sum(int(r.get("duracao_min", 0)) for r in historico)
    return {
        "quantidade": len(historico),
        "total_minutos": total_min,
    }


def renomear_tarefa_historico(antigo: str, novo: str) -> int:
    """Troca o nome de uma tarefa em todos os registros do histórico.

    Devolve quantos registros foram alterados."""
    historico = carregar_historico()
    alterados = 0
    for reg in historico:
        if reg.get("tarefa") == antigo:
            reg["tarefa"] = novo
            alterados += 1
    if alterados:
        _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})
    return alterados


# --------------------------------------------------------------------------- #
# Estatísticas (agregações usadas na aba Estatísticas)
# --------------------------------------------------------------------------- #
def minutos_por_dia(dias: int) -> dict[str, int]:
    """Minutos de foco somados por dia (AAAA-MM-DD) nos últimos `dias` dias.

    Todos os dias do período entram no resultado, mesmo com 0 minutos,
    em ordem cronológica — pronto para desenhar o gráfico."""
    hoje = date.today()
    resultado = {
        (hoje - timedelta(days=i)).isoformat(): 0
        for i in range(dias - 1, -1, -1)
    }
    for reg in carregar_historico():
        dia = str(reg.get("data", ""))[:10]
        if dia in resultado:
            resultado[dia] += int(reg.get("duracao_min", 0))
    return resultado


def pomodoros_do_dia(dia: str | None = None) -> int:
    """Quantidade de pomodoros COMPLETOS (não parciais) de um dia
    (padrão: hoje). Usado para a meta diária."""
    dia = dia or date.today().isoformat()
    return sum(
        1 for reg in carregar_historico()
        if str(reg.get("data", ""))[:10] == dia and not reg.get("parcial")
    )


def calcular_streak() -> int:
    """Dias consecutivos (terminando hoje ou ontem) com ao menos um
    pomodoro completo. Hoje ainda sem registro não quebra a sequência."""
    dias_com_foco = {
        str(reg.get("data", ""))[:10]
        for reg in carregar_historico()
        if not reg.get("parcial")
    }
    hoje = date.today()
    # A sequência pode começar hoje ou, se hoje ainda não teve foco, ontem.
    inicio = hoje if hoje.isoformat() in dias_com_foco else hoje - timedelta(days=1)
    streak = 0
    dia = inicio
    while dia.isoformat() in dias_com_foco:
        streak += 1
        dia -= timedelta(days=1)
    return streak
