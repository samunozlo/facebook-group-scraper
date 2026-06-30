from playwright.sync_api import sync_playwright
import pandas as pd
import time
import re
import hashlib
import random
from datetime import datetime
from pathlib import Path


# ======================================================
# CONFIGURACIÓN
# ======================================================

GROUP_URL = "https://www.facebook.com/groups/1745396122434438/"

# Meta total acumulada en el CSV
TARGET_TOTAL_POSTS = 1000

# Cantidad máxima de scrolls por ejecución
MAX_SCROLLS = 400

# Archivo de sesión guardada
STATE_FILE = "facebook_state.json"

# Archivo de salida
OUTPUT_CSV = "facebook_posts_grupo_1745396122434438.csv"

# Guarda cada N publicaciones nuevas
SAVE_EVERY_NEW_POSTS = 10

# Pausas
WAIT_INITIAL_SECONDS = 10
WAIT_AFTER_SCROLL_MIN = 5
WAIT_AFTER_SCROLL_MAX = 9

# Si pasan muchos scrolls sin posts nuevos, se detiene
MAX_SCROLLS_WITHOUT_NEW = 35

# Evita guardar textos demasiado cortos o basura
MIN_TEXT_LENGTH = 20


# ======================================================
# FUNCIONES AUXILIARES
# ======================================================

def normalizar_texto(texto: str) -> str:
    texto = texto or ""
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def crear_hash(texto: str) -> str:
    texto_norm = normalizar_texto(texto).lower()
    return hashlib.sha256(texto_norm.encode("utf-8")).hexdigest()


def cargar_base_existente():
    path = Path(OUTPUT_CSV)

    if not path.exists():
        print("No existe CSV previo. Se iniciará extracción desde cero.")
        return [], set()

    df = pd.read_csv(path)

    if df.empty:
        print("El CSV existe, pero está vacío. Se iniciará extracción desde cero.")
        return [], set()

    if "post_texto" not in df.columns:
        print("El CSV existe, pero no tiene columna post_texto. Se iniciará extracción desde cero.")
        return [], set()

    if "content_hash" not in df.columns:
        df["content_hash"] = df["post_texto"].astype(str).apply(crear_hash)

    df = df.drop_duplicates(subset=["content_hash"]).reset_index(drop=True)

    registros = df.to_dict("records")
    hashes = set(df["content_hash"].dropna().astype(str))

    print(f"CSV previo encontrado: {OUTPUT_CSV}")
    print(f"Posts acumulados previamente: {len(registros)}")

    return registros, hashes


def guardar_csv(registros):
    if not registros:
        print("No hay registros para guardar.")
        return pd.DataFrame()

    df = pd.DataFrame(registros)

    if "content_hash" not in df.columns:
        df["content_hash"] = df["post_texto"].astype(str).apply(crear_hash)

    df = df.drop_duplicates(subset=["content_hash"]).reset_index(drop=True)

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"CSV guardado: {OUTPUT_CSV} | Posts acumulados: {len(df)}")

    return df


def detectar_login_checkpoint_o_bloqueo(page) -> bool:
    url_actual = page.url.lower()

    if "login" in url_actual or "checkpoint" in url_actual:
        return True

    textos_alerta = [
        "iniciar sesión",
        "log in",
        "checkpoint",
        "confirma tu identidad",
        "confirm your identity",
        "captcha",
        "security check",
        "control de seguridad",
        "bloqueado temporalmente",
        "temporarily blocked",
    ]

    try:
        body = page.locator("body").inner_text(timeout=4000).lower()
        return any(t in body for t in textos_alerta)
    except Exception:
        return False


def expandir_ver_mas(page):
    etiquetas = [
        "Ver más",
        "See more",
        "Mostrar más",
    ]

    for label in etiquetas:
        try:
            botones = page.locator(f"text={label}")
            total = min(botones.count(), 10)

            for i in range(total):
                try:
                    botones.nth(i).click(timeout=1200)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

        except Exception:
            pass


# ======================================================
# SCRAPER PRINCIPAL
# ======================================================

def extraer_posts_incremental():
    if not Path(STATE_FILE).exists():
        raise FileNotFoundError(
            f"No se encontró {STATE_FILE}. Primero ejecuta: python login_and_save_state.py"
        )

    registros, hashes_existentes = cargar_base_existente()

    if len(registros) >= TARGET_TOTAL_POSTS:
        print(f"Ya tienes {len(registros)} posts, que es igual o superior a la meta de {TARGET_TOTAL_POSTS}.")
        return pd.DataFrame(registros)

    nuevos_en_corrida = 0
    nuevos_desde_ultimo_guardado = 0
    scrolls_sin_nuevos = 0

    browser = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                slow_mo=200
            )

            context = browser.new_context(
                storage_state=STATE_FILE,
                locale="es-ES",
                viewport={"width": 1366, "height": 768}
            )

            page = context.new_page()

            print(f"Abriendo grupo: {GROUP_URL}")

            page.goto(
                GROUP_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            time.sleep(WAIT_INITIAL_SECONDS)

            if detectar_login_checkpoint_o_bloqueo(page):
                print("Facebook pidió login, checkpoint o bloqueo. Se detiene.")
                guardar_csv(registros)
                browser.close()
                return pd.DataFrame(registros)

            for scroll in range(1, MAX_SCROLLS + 1):
                print("\n" + "=" * 60)
                print(f"Scroll {scroll}/{MAX_SCROLLS}")
                print(f"Posts acumulados: {len(registros)} / {TARGET_TOTAL_POSTS}")

                nuevos_este_scroll = 0

                expandir_ver_mas(page)

                elementos = page.locator("div[data-ad-rendering-role='story_message']")
                total_elementos = elementos.count()

                print(f"Elementos de texto encontrados en pantalla: {total_elementos}")

                for i in range(total_elementos):
                    try:
                        texto = elementos.nth(i).inner_text(timeout=3000)
                        texto = normalizar_texto(texto)

                        if not texto:
                            continue

                        if len(texto) < MIN_TEXT_LENGTH:
                            continue

                        content_hash = crear_hash(texto)

                        if content_hash in hashes_existentes:
                            continue

                        hashes_existentes.add(content_hash)

                        registros.append({
                            "fecha_extraccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "grupo_url": GROUP_URL,
                            "post_texto": texto,
                            "longitud_texto": len(texto),
                            "content_hash": content_hash,
                            "scroll_origen": scroll
                        })

                        nuevos_en_corrida += 1
                        nuevos_desde_ultimo_guardado += 1
                        nuevos_este_scroll += 1

                        print(f"Post nuevo capturado: {len(registros)}")

                        if nuevos_desde_ultimo_guardado >= SAVE_EVERY_NEW_POSTS:
                            guardar_csv(registros)
                            nuevos_desde_ultimo_guardado = 0

                        if len(registros) >= TARGET_TOTAL_POSTS:
                            print("Meta alcanzada.")
                            break

                    except Exception as e:
                        print(f"No se pudo procesar un elemento: {e}")

                if len(registros) >= TARGET_TOTAL_POSTS:
                    break

                if nuevos_este_scroll == 0:
                    scrolls_sin_nuevos += 1
                    print(f"Scrolls seguidos sin posts nuevos: {scrolls_sin_nuevos}")
                else:
                    scrolls_sin_nuevos = 0

                if scrolls_sin_nuevos >= MAX_SCROLLS_WITHOUT_NEW:
                    print("Demasiados scrolls sin posts nuevos. Se detiene para evitar desgaste.")
                    break

                guardar_csv(registros)

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                pausa = random.randint(WAIT_AFTER_SCROLL_MIN, WAIT_AFTER_SCROLL_MAX)
                print(f"Pausa de {pausa} segundos...")
                time.sleep(pausa)

                if detectar_login_checkpoint_o_bloqueo(page):
                    print("Facebook mostró login, checkpoint o bloqueo durante la extracción. Se detiene.")
                    break

            browser.close()
            browser = None

    except KeyboardInterrupt:
        print("\nProceso interrumpido manualmente. Se guarda lo acumulado.")

    except Exception as e:
        print(f"\nError durante la extracción: {e}")
        print("Se guarda lo acumulado antes de cerrar.")

    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass

        df_final = guardar_csv(registros)

        print("\nExtracción finalizada.")
        print(f"Posts nuevos en esta corrida: {nuevos_en_corrida}")
        print(f"Posts acumulados en CSV: {len(df_final)}")
        print(f"Archivo final: {OUTPUT_CSV}")

        return df_final


# ======================================================
# EJECUCIÓN
# ======================================================

if __name__ == "__main__":
    df = extraer_posts_incremental()
    print(df.head())