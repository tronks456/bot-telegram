import time
import requests
from curl_cffi import requests as curl_requests


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

TELEGRAM_TOKEN = "8852938820:AAEno_bwq7JAeA3N0zzTVhiWG-NLRPleZco"
TELEGRAM_CHAT_ID = "-1004467197117"

# Tu API Key de The Odds API
ODDS_API_KEY = "5fb0f799f7d37bbc1dfa3a848a2e66d1"

URL_TELEGRAM = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
)

URL_SOFASCORE = (
    "https://www.sofascore.com/api/v1/sport/football/events/live"
)

# Configurado en 180 segundos (3 minutos) para evitar bloqueos 403
INTERVALO_ESCANEO = 180

# Umbral para comenzar un episodio de presión
UMBRAL_ALERTA = 75

# Por debajo de este valor consideramos que
# el episodio de presión terminó
UMBRAL_REARME = 55


# ==========================================================
# MEMORIA
# ==========================================================

estadisticas_anteriores = {}
episodios_activos = {}
numero_episodio = {}


# ==========================================================
# TELEGRAM
# ==========================================================

def enviar_mensaje_telegram(mensaje):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        respuesta = requests.post(
            URL_TELEGRAM,
            json=payload,
            timeout=10
        )
        datos = respuesta.json()

        if respuesta.status_code == 200 and datos.get("ok"):
            print("✅ Telegram: alerta enviada.")
            return True
        else:
            print("❌ Telegram rechazó el mensaje:")
            print(datos)
            return False
    except Exception as error:
        print("❌ Error Telegram:")
        print(error)
        return False


# ==========================================================
# OBTENER CUOTAS DESDE THE ODDS API
# ==========================================================

def obtener_cuotas_odds_api(equipo_local, equipo_visitante):
    # Valores por defecto en caso de no hallar coincidencia exacta
    cuotas = {
        "a_1xbet": "1.85",
        "a_365": "1.80",
        "b_1xbet": "1.90",
        "b_365": "1.85"
    }

    try:
        url_odds = (
            f"https://api.the-odds-api.com/v4/sports/soccer/odds/"
            f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
        )
        respuesta = requests.get(url_odds, timeout=10)
        
        if respuesta.status_code != 200:
            return cuotas

        eventos = respuesta.json()
        
        # Buscamos un partido que coincida con los nombres
        for evento in eventos:
            home_api = str(evento.get("home_team", "")).lower()
            away_api = str(evento.get("away_team", "")).lower()

            if equipo_local.lower() in home_api or home_api in equipo_local.lower():
                bookmakers = evento.get("bookmakers", [])
                for bookmaker in bookmakers:
                    book_key = bookmaker.get("key")
                    if book_key in ["1xbet", "bet365"]:
                        markets = bookmaker.get("markets", [])
                        for market in markets:
                            if market.get("key") == "totals":
                                outcomes = market.get("outcomes", [])
                                for out in outcomes:
                                    if out.get("name") == "Over" and out.get("point") == 2.5:
                                        precio = str(out.get("price", "1.85"))
                                        if book_key == "1xbet":
                                            cuotas["a_1xbet"] = precio
                                        elif book_key == "bet365":
                                            cuotas["a_365"] = precio
    except Exception as e:
        print(f"⚠️ Error consultando The Odds API: {e}")

    return cuotas


# ==========================================================
# OBTENER ESTADÍSTICAS DE SOFASCORE
# ==========================================================

def obtener_estadisticas(id_partido):
    resultado = {
        "remates_totales_local": 0,
        "remates_totales_visitante": 0,
        "tiros_arco_local": 0,
        "tiros_arco_visitante": 0,
        "corners_local": 0,
        "corners_visitante": 0
    }

    try:
        url_stats = (
            f"https://www.sofascore.com/api/v1/event/"
            f"{id_partido}/statistics"
        )

        respuesta = curl_requests.get(
            url_stats,
            impersonate="chrome120",
            timeout=10
        )

        if respuesta.status_code != 200:
            return resultado

        datos = respuesta.json()

        for periodo in datos.get("statistics", []):
            for grupo in periodo.get("groups", []):
                for item in grupo.get("statisticsItems", []):
                    nombre = str(
                        item.get("name", "")
                    ).strip().lower()

                    try:
                        local = int(item.get("home", 0))
                    except:
                        local = 0

                    try:
                        visitante = int(item.get("away", 0))
                    except:
                        visitante = 0

                    if nombre in ("total shots", "shots"):
                        resultado["remates_totales_local"] = local
                        resultado["remates_totales_visitante"] = visitante

                    elif nombre in ("shots on target", "shots on goal"):
                        resultado["tiros_arco_local"] = local
                        resultado["tiros_arco_visitante"] = visitante

                    elif nombre in ("corner kicks", "corners"):
                        resultado["corners_local"] = local
                        resultado["corners_visitante"] = visitante

    except Exception as error:
        print(f"❌ Error estadísticas {id_partido}: {error}")

    return resultado


# ==========================================================
# OBTENER MINUTO Y ETAPA
# ==========================================================

def obtener_minuto_y_etapa(partido):
    try:
        status = partido.get("status", {})
        minuto = status.get("currentLength")
        
        descripcion = str(status.get("description", "")).lower()
        if "1st" in descripcion or "1" in str(status.get("code", "")):
            tiempo_etapa = "1er Tiempo"
        elif "2nd" in descripcion or "2" in str(status.get("code", "")):
            tiempo_etapa = "2do Tiempo"
        else:
            tiempo_etapa = "En vivo"

        if minuto is not None:
            return int(minuto), tiempo_etapa
    except:
        pass
    return 0, "En vivo"


# ==========================================================
# LIMITAR VALOR
# ==========================================================

def limitar(valor, minimo=0, maximo=100):
    return max(minimo, min(maximo, valor))


# ==========================================================
# CALCULAR PRESIÓN
# ==========================================================

def calcular_presion(
    remates, remates_rival,
    arco, arco_rival,
    corners, corners_rival,
    nuevos_arco
):
    puntos_arco = limitar(arco * 5, 0, 30)
    puntos_remates = limitar(remates * 1.5, 0, 20)
    puntos_corners = limitar(corners * 3, 0, 15)

    total_remates = remates + remates_rival
    if total_remates > 0:
        porcentaje = (remates / total_remates) * 100
    else:
        porcentaje = 50

    if porcentaje >= 80:
        puntos_dominio = 15
    elif porcentaje >= 70:
        puntos_dominio = 12
    elif porcentaje >= 60:
        puntos_dominio = 9
    elif porcentaje >= 55:
        puntos_dominio = 6
    else:
        puntos_dominio = 0

    diferencia = arco - arco_rival
    puntos_diferencia = limitar(diferencia * 3, 0, 10)
    puntos_recientes = limitar(nuevos_arco * 5, 0, 10)

    indice = (
        puntos_arco +
        puntos_remates +
        puntos_corners +
        puntos_dominio +
        puntos_diferencia +
        puntos_recientes
    )

    return round(limitar(indice), 1)


# ==========================================================
# ANALIZAR PARTIDO
# ==========================================================

def analizar_partido(
    id_partido, home, away, liga_nombre, pais,
    minuto, tiempo_etapa, stats
):
    remates_l = stats["remates_totales_local"]
    remates_v = stats["remates_totales_visitante"]
    arco_l = stats["tiros_arco_local"]
    arco_v = stats["tiros_arco_visitante"]
    corners_l = stats["corners_local"]
    corners_v = stats["corners_visitante"]

    if id_partido not in estadisticas_anteriores:
        estadisticas_anteriores[id_partido] = {
            "arco_l": arco_l,
            "arco_v": arco_v
        }
        return

    anteriores = estadisticas_anteriores[id_partido]

    nuevos_l = max(0, arco_l - anteriores["arco_l"])
    nuevos_v = max(0, arco_v - anteriores["arco_v"])

    estadisticas_anteriores[id_partido] = {
        "arco_l": arco_l,
        "arco_v": arco_v
    }

    presion_local = calcular_presion(
        remates_l, remates_v, arco_l, arco_v, corners_l, corners_v, nuevos_l
    )
    presion_visitante = calcular_presion(
        remates_v, remates_l, arco_v, arco_l, corners_v, corners_l, nuevos_v
    )

    print(
        f"📊 Presión: {home} {presion_local}/100 "
        f"| {away} {presion_visitante}/100"
    )

    if presion_local >= presion_visitante:
        indice = presion_local
        dominador = home
        asediado = away
    else:
        indice = presion_visitante
        dominador = away
        asediado = home

    episodio_activo = episodios_activos.get(id_partido, False)

    if indice <= UMBRAL_REARME:
        if episodio_activo:
            print(
                f"📉 Episodio terminado: {home} vs {away} "
                f"| Presión {indice}/100"
            )
        episodios_activos[id_partido] = False
        return

    if indice < UMBRAL_ALERTA:
        return

    if episodio_activo:
        return

    episodios_activos[id_partido] = True

    puntos_calculados = round(indice / 6, 1)

    # Obtenemos las cuotas reales desde The Odds API
    cuotas = obtener_cuotas_odds_api(home, away)

    mensaje = (
        f"🌍 RADAR PREDICTIVO - {pais.upper()} 🌍\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Torneo: {liga_nombre}\n"
        f"⚔️ Partido: {home} vs {away}\n"
        f"⏱️ Tiempo: {tiempo_etapa} (Min {minuto}')\n"
        f"📊 Puntaje Matemático: {puntos_calculados} pts (>= 12)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Dominador Local: {dominador}\n"
        f"🛡️ Rival Asediado: {asediado}\n\n"
        f"⚽️ Remates Totales: {stats['remates_totales_local']} - {stats['remates_totales_visitante']}\n"
        f"🎯 Remates al Arco: {stats['tiros_arco_local']} - {stats['tiros_arco_visitante']}\n"
        f"🚩 Córners Activos: {stats['corners_local']} - {stats['corners_visitante']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Estado: 🔴 PRESIÓN CRÍTICA DETECTADA\n"
        f"📊 Dominio Territorial: ⭐️⭐️⭐️ (Alta Probabilidad)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 ENTRADAS RECOMENDADAS (OPCIONES VIP):\n\n"
        f"▶️ **Opción A (Goles):** Más de 2.5 Goles\n"
        f"   ├ 🟦 [1xBet (@{cuotas['a_1xbet']})](https://1xbet.com)\n"
        f"   └ 🟩 [Bet365 (@{cuotas['a_365']})](https://www.bet365.com)\n\n"
        f"▶️ **Opción B (Córners):** Más de 7.5 Córners\n"
        f"   ├ 🟦 [1xBet (@{cuotas['b_1xbet']})](https://1xbet.com)\n"
        f"   └ 🟩 [Bet365 (@{cuotas['b_365']})](https://www.bet365.com)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **GUÍA RÁPIDA PARA OPERAR:**\n"
        f"1️⃣ Elige la opción que mejor se adapte a tu análisis.\n"
        f"2️⃣ Entra a tu casa de apuestas con los enlaces directos.\n"
        f"3️⃣ ¡Gestiona tu capital con responsabilidad! 🚀"
    )

    enviar_mensaje_telegram(mensaje)


# ==========================================================
# INICIO Y BUCLE PRINCIPAL
# ==========================================================

print("")
print("==============================================")
print("🤖 MONITOR GLOBAL CON THE ODDS API INTEGRADO")
print("==============================================")
print("")
print(f"🔥 Alerta desde: {UMBRAL_ALERTA}/100")
print(f"📉 Rearme: {UMBRAL_REARME}/100")
print(f"⏱ Escaneo: {INTERVALO_ESCANEO} segundos (3 minutos)")
print("")

enviar_mensaje_telegram(
    "✅ *Monitor global con Odds API iniciado.*\n\n"
    "📊 Listos para capturar cuotas de mercado y presión en vivo."
)

while True:
    try:
        respuesta = curl_requests.get(
            URL_SOFASCORE,
            impersonate="chrome120",
            timeout=15
        )

        if respuesta.status_code != 200:
            print("❌ Error Sofascore:", respuesta.status_code)
            time.sleep(INTERVALO_ESCANEO)
            continue

        datos = respuesta.json()
        partidos = datos.get("events", [])

        partidos_pro = 0
        partidos_en_juego = 0
        partidos_actuales = set()

        print(f"\n🔄 Revisados {len(partidos)} partidos globales\n")

        for partido in partidos:
            id_partido = partido.get("id")
            if not id_partido:
                continue

            tournament = partido.get("tournament", {})
            liga_nombre = tournament.get("name", "Sin torneo")
            
            category = tournament.get("category", {})
            pais = category.get("name", "Internacional")
            
            # FILTRO DE LIGAS PROFESIONALES (Excluimos juveniles, reservas, amateur)
            liga_lower = liga_nombre.lower()
            if any(term in liga_lower for term in ["u17", "u19", "u20", "u21", "u23", "sub-", "reserve", "reserves", "amateur", "youth"]):
                continue

            status = partido.get("status", {})
            tipo_estado = str(status.get("type", "")).lower()

            if tipo_estado != "inprogress":
                continue

            # OBTENEMOS EL MINUTO ANTES DE PROCESAR NADA
            minuto, tiempo_etapa = obtener_minuto_y_etapa(partido)

            # 🛡️ FILTRO ESTRICTO DE TIEMPO: Solo partidos antes del minuto 80
            if minuto > 80 or minuto == 0:
                continue

            partidos_pro += 1
            partidos_actuales.add(id_partido)
            partidos_en_juego += 1

            home = partido.get("homeTeam", {}).get("name", "Desconocido")
            away = partido.get("awayTeam", {}).get("name", "Desconocido")

            stats = obtener_estadisticas(id_partido)

            print(f"[{pais}] {home} vs {away}")
            print(f"    Torneo: {liga_nombre}")
            print(f"    Minuto: {minuto}' ({tiempo_etapa})")

            analizar_partido(
                id_partido, home, away, liga_nombre, pais,
                minuto, tiempo_etapa, stats
            )

        for id_guardado in list(estadisticas_anteriores.keys()):
            if id_guardado not in partidos_actuales:
                del estadisticas_anteriores[id_guardado]

        for id_guardado in list(episodios_activos.keys()):
            if id_guardado not in partidos_actuales:
                del episodios_activos[id_guardado]

        print(f"\n🌍 Ligas Profesionales Globales: {partidos_pro}")
        print(f"⚽ En juego: {partidos_en_juego}")
        print(f"🧠 En memoria: {len(estadisticas_anteriores)}")
        print(f"🔥 Episodios activos: {sum(episodios_activos.values())}")
        print(f"⏳ Próximo escaneo en {INTERVALO_ESCANEO} segundos...")

    except Exception as error:
        print("\n❌ ERROR EN EL CICLO:")
        print(error)
        print("")

    time.sleep(INTERVALO_ESCANEO)