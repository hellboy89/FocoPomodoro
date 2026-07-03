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
from datetime import datetime, timedelta

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


def registrar_pomodoro(tarefa: str, duracao_min: int, dias_manter: int = 0) -> dict:
    """Acrescenta um pomodoro concluído ao histórico e o devolve.

    Se `dias_manter` > 0, poda registros antigos após gravar."""
    historico = carregar_historico()
    registro = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tarefa": tarefa.strip() or "(sem descrição)",
        "duracao_min": int(duracao_min),
    }
    historico.append(registro)
    _gravar_json(ARQUIVO_HISTORICO, {"pomodoros": historico})
    if dias_manter and dias_manter > 0:
        podar_historico(dias_manter)
    return registro


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
