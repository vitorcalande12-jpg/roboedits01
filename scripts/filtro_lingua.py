#!/usr/bin/env python3
"""
Filtro de língua da legenda: só fica na legenda o que é falado na língua do corte (padrão português).

Fala em outra língua (personagem do jogo em inglês, cena de história, rádio, música, vídeo tocando na live)
sai da legenda. Para cada trecho que o Whisper transcreveu:
  1. ouve o próprio áudio do trecho e pergunta ao Whisper qual língua é (trechos de 1 s ou mais);
  2. confere o texto: trecho cheio de palavras comuns do inglês/espanhol e sem palavras de português sai.

Uso dentro dos scripts de legenda:
  from filtro_lingua import manter_lingua
  segs = manter_lingua(modelo_whisper, audio_16k, segs, "pt")
"""
import re, unicodedata

SR = 16000

PT = {"que", "não", "nao", "é", "eu", "você", "voce", "vc", "mano", "cara", "tá", "ta", "está", "esta", "isso",
      "aqui", "uma", "um", "pra", "pro", "com", "de", "do", "da", "no", "na", "meu", "minha", "ele", "ela",
      "vai", "vou", "foi", "tem", "ter", "então", "entao", "agora", "também", "tambem", "muito", "porque",
      "por", "mas", "mais", "nós", "nos", "gente", "olha", "ai", "aí", "né", "ne", "tô", "to", "estou",
      "bom", "como", "quando", "onde", "só", "so", "já", "ja", "ainda", "nada", "tudo", "sim", "velho",
      "irmão", "irmao", "caralho", "porra", "nossa", "pode", "faz", "fazer", "dele", "dela", "seu", "sua",
      "os", "as", "dos", "das", "num", "numa", "esse", "essa", "lá", "la", "vamo", "bora", "uai", "oxe"}
EN = {"the", "you", "i", "is", "are", "what", "this", "that", "it", "and", "of", "in", "on", "for",
      "with", "my", "your", "we", "they", "he", "she", "was", "be", "have", "has", "don't", "dont",
      "can", "will", "just", "get", "got", "go", "going", "know", "want", "here", "there", "now", "all",
      "let's", "lets", "yeah", "yes", "him", "her", "us", "them", "not",
      "out", "up", "if", "but", "at", "from", "about", "like", "right", "well", "gonna", "wanna",
      "i'm", "im", "it's", "you're", "we're", "that's", "what's", "where", "who", "why", "how", "an", "am"}
ES = {"el", "los", "las", "y", "es", "qué", "pero", "muy", "estoy", "eres", "tú", "usted", "ahora", "aquí",
      "hola", "gracias", "señor", "hombre", "pues", "nosotros", "ellos", "bueno", "porqué", "cómo"}
OUTRAS = {"en": EN, "es": ES}


def _palavras(texto):
    t = unicodedata.normalize("NFC", texto.lower())
    return re.findall(r"[a-zà-ÿ']+", t)


def lingua_pelo_texto(texto, alvo="pt"):
    """'outra' quando o texto claramente não é da língua do corte; 'alvo' quando é; None se não dá para saber."""
    ps = _palavras(texto)
    if len(ps) < 3:  # "let's go", "oh my god" soltos: o streamer brasileiro também fala; o áudio decide
        return None
    if alvo != "pt":
        return None  # a lista de palavras é só para cortes em português
    n_pt = sum(p in PT for p in ps)
    n_out = max(sum(p in s for p in ps) for s in OUTRAS.values())
    if n_out >= 2 and n_out >= 2 * max(n_pt, 1) - 1 and n_out / len(ps) >= 0.34:
        return "outra"
    if n_pt >= 1 and n_pt >= n_out:
        return "alvo"
    return None


def lingua_pelo_audio(modelo, trecho):
    """(língua, probabilidade) que o Whisper ouve neste trecho de áudio."""
    try:
        lang, prob, todas = modelo.detect_language(audio=trecho)  # faster-whisper >= 1.1
        return lang, prob, dict(todas or [])
    except Exception:
        pass
    try:  # versões antigas: pelo modelo interno
        import numpy as np
        fe = modelo.feature_extractor
        feats = fe(trecho)[:, : fe.nb_max_frames]
        enc = modelo.encode(feats)
        res = modelo.model.detect_language(enc)[0]
        todas = {t[2:-2]: p for t, p in res}
        lang = max(todas, key=todas.get)
        return lang, todas[lang], todas
    except Exception:
        return None, 0.0, {}


def manter_lingua(modelo, audio, segs, alvo="pt", log=print):
    """Recebe os segmentos do faster-whisper (já materializados em lista) e devolve só os da língua do corte."""
    alvo = (alvo or "pt").lower()
    if alvo in ("", "auto"):
        alvo = "pt"
    ficam, tirados = [], []
    for s in segs:
        texto = (s.text or "").strip()
        dur = float(s.end) - float(s.start)
        veredito = None
        if dur >= 1.0:
            a = audio[int(max(0, s.start) * SR): int(s.end * SR)]
            lang, prob, todas = lingua_pelo_audio(modelo, a)
            p_alvo = todas.get(alvo, prob if lang == alvo else 0.0)
            certeza = 0.5 if dur >= 2.0 else 0.75  # trecho curto: só tira com muita certeza
            if lang and lang != alvo and prob >= certeza and p_alvo < 0.25:
                veredito = "outra"
            elif lang == alvo or p_alvo >= 0.35:
                veredito = "alvo"
        pelo_texto = lingua_pelo_texto(texto, alvo)
        # texto inequívoco em inglês/espanhol tira mesmo se o áudio ficou na dúvida;
        # áudio dizendo outra língua tira, a não ser que o texto seja claramente português
        if pelo_texto == "outra" or (veredito == "outra" and pelo_texto != "alvo"):
            tirados.append(s)
        else:
            ficam.append(s)
    if tirados:
        log(f"OUTRA_LINGUA {len(tirados)} trecho(s) fora de '{alvo}' tirados da legenda: "
            + " | ".join(f"[{t.start:.1f}s] {t.text.strip()[:40]}" for t in tirados[:6]))
    return ficam
