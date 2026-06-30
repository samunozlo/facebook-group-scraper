import pandas as pd
import re
import hashlib
from pathlib import Path


# ======================================================
# CONFIGURACIÓN
# ======================================================

INPUT_CSV = "facebook_posts_grupo_1745396122434438.csv"
OUTPUT_CSV = "facebook_posts_grupo_1745396122434438_enriquecido.csv"


PRODUCT_CATEGORIES = {
    "pizza": ["pizza", "pizzas", "pizzería", "pizzeria", "pepperoni"],
    "hamburguesa": ["hamburguesa", "hamburguesas", "burger", "burguer"],
    "perros calientes": ["perro caliente", "perros calientes", "hot dog", "hotdog"],
    "lechona": ["lechona"],
    "tamales": ["tamal", "tamales"],
    "almuerzos/corrientazo": [
        "almuerzo", "almuerzos", "corrientazo", "ejecutivo",
        "menú del día", "menu del dia", "menú ejecutivo"
    ],
    "postres/repostería": [
        "postre", "postres", "torta", "tortas", "brownie",
        "3 leches", "tres leches", "cacao", "galleta",
        "panadería", "repostería", "oreo"
    ],
    "comida rápida": [
        "comida rápida", "papas", "salchipapa", "patacón",
        "patacon", "picada", "nachos"
    ],
    "mexicana": ["taco", "tacos", "mexicana", "burrito", "quesadilla"],
    "parrilla/asados": ["parrilla", "asados", "chorizo", "carne asada"],
    "salsas": ["salsa", "salsas", "picante", "picantes", "hogao"],
    "saludable": ["saludable", "ensalada", "vegano", "vegetariano", "fit"],
    "brasileña": ["brasileño", "brasileños", "brasileña", "maracanada", "favela"],
}


ADDRESS_RE = re.compile(
    r"\b(?:calle|cll|cl\.?|carrera|cra\.?|kr\.?|kra\.?|cr\.?|avenida|av\.?|diagonal|diag\.?|transversal|tv\.?)\s*"
    r"\d{1,3}\s*[a-zA-Z]?\s*(?:#|n[°o]\.?|num(?:ero)?\.?|-)\s*"
    r"\d{1,3}\s*[a-zA-Z]?(?:\s*[- ]\s*\d{1,3}\s*[a-zA-Z]?)?",
    flags=re.IGNORECASE
)

ADDRESS_RE_2 = re.compile(
    r"\b(?:calle|cll|cl\.?|carrera|cra\.?|kr\.?|kra\.?|cr\.?)\s*"
    r"\d{1,3}\s*[a-zA-Z]?\s*[a-zA-Z]?\s*#\s*"
    r"\d{1,3}\s*[a-zA-Z]?\s+\d{1,3}\s*[a-zA-Z]?",
    flags=re.IGNORECASE
)

BARRIO_RE = re.compile(
    r"\bbarrio\s+([A-Za-zÁÉÍÓÚáéíóúÑñ ]{2,40})(?=\s+(?:calle|carrera|cra|cl|kr)|[,.]|$)",
    flags=re.IGNORECASE
)


# ======================================================
# FUNCIONES
# ======================================================

def normalizar_texto(texto):
    texto = texto or ""
    return re.sub(r"\s+", " ", str(texto)).strip()


def title_clean(texto):
    texto = normalizar_texto(texto)
    texto = re.sub(r"\s*[|•·:;,-]\s*$", "", texto)
    return texto[:120]


def split_hashtag_camel(tag):
    tag = tag.strip("#")
    tag = re.sub(r"(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÑ])", " ", tag)
    tag = re.sub(r"[_-]+", " ", tag)
    return tag.strip().title()


def es_mal_candidato_nombre(nombre):
    nombre_limpio = nombre.lower().strip(" .,:;!¡¿?")

    ciudades = {
        "medellín", "medellin", "bogotá", "bogota", "colombia",
        "antioquia", "castilla", "santa cruz", "campo valdés",
        "campo valdes", "aranjuez"
    }

    if not nombre or len(nombre) < 3:
        return True

    if nombre_limpio in ciudades:
        return True

    malos_inicios = (
        "te invitamos", "disponible", "domicilios", "hoy ",
        "todo ", "delicioso", "deliciosos", "los ", "las ",
        "el favorito", "la combinación", "la combinacion"
    )

    if nombre_limpio.startswith(malos_inicios):
        return True

    malos_terminos = [
        "whatsapp", "wa.me", "dm", "pedido ahora", "teléfono",
        "telefono", "domicilio", "ver más", "ver mas", "ver menos"
    ]

    if any(x in nombre_limpio for x in malos_terminos):
        return True

    if len(nombre.split()) > 7:
        return True

    return False


def extraer_nombre_negocio(texto):
    texto = normalizar_texto(texto)
    candidatos = []

    # Caso: "— Oliser Chef y Tradición en Horno · Medellín"
    for m in re.finditer(r"[—–]\s*([^·|\n]{3,80})\s*[·|]", texto):
        candidatos.append(title_clean(m.group(1)))

    # Caso: "En Verde Sabores Saludables nos adaptamos..."
    verbos = (
        r"(?:tenemos|te esperamos|disfruta|encuentras|preparamos|"
        r"nos adaptamos|ofrecemos|hay|puedes|estamos|somos|"
        r"te compartimos|queremos)"
    )

    patron_en = (
        r"\b[Ee]n\s+"
        r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&'’\.\- ]{3,70}?)"
        r"(?=\s+" + verbos + r"\b|[,.;:!])"
    )

    for m in re.finditer(patron_en, texto):
        candidatos.append(title_clean(m.group(1)))

    # Fallback: hashtags comerciales
    hashtags = re.findall(r"#([A-Za-zÁÉÍÓÚÑáéíóúñ0-9_]{4,40})", texto)

    for h in hashtags:
        h_lower = h.lower()

        if any(k in h_lower for k in [
            "pizza", "sabor", "chef", "cafe", "café", "burg",
            "food", "rest", "queso", "tremend", "antojitos",
            "oliser", "verde"
        ]):
            candidatos.append(split_hashtag_camel(h))

    limpios = []

    for c in candidatos:
        c = normalizar_texto(c)
        c = re.split(
            r"\s+(?:te compartimos|tenemos|nos adaptamos|preparamos|ofrecemos)\b",
            c,
            flags=re.IGNORECASE
        )[0]

        c = title_clean(c)

        if es_mal_candidato_nombre(c):
            continue

        if c not in limpios:
            limpios.append(c)

    if limpios:
        return limpios[0]

    return ""


def extraer_direcciones(texto):
    texto = normalizar_texto(texto)
    direcciones = []

    for patron in [ADDRESS_RE_2, ADDRESS_RE]:
        for m in patron.finditer(texto):
            direccion = title_clean(m.group(0))
            direccion = re.sub(r"\s+", " ", direccion)

            if direccion.lower() not in [d.lower() for d in direcciones]:
                direcciones.append(direccion)

    return " | ".join(direcciones)


def extraer_barrios(texto):
    texto = normalizar_texto(texto)
    barrios = []

    for m in BARRIO_RE.finditer(texto):
        barrio = title_clean(m.group(1))

        if barrio and barrio.lower() not in [b.lower() for b in barrios]:
            barrios.append(barrio)

    return " | ".join(barrios)


def extraer_productos(texto):
    texto_lower = str(texto).lower()

    categorias = []
    keywords = []

    for categoria, palabras in PRODUCT_CATEGORIES.items():
        for palabra in palabras:
            if palabra in texto_lower:
                if categoria not in categorias:
                    categorias.append(categoria)

                if palabra not in keywords:
                    keywords.append(palabra)

    return " | ".join(categorias), " | ".join(keywords)


# ======================================================
# EJECUCIÓN
# ======================================================

df = pd.read_csv(INPUT_CSV)

df["post_texto"] = df["post_texto"].fillna("").astype(str)

df["nombre_negocio_estimado"] = df["post_texto"].apply(extraer_nombre_negocio)
df["direcciones_detectadas"] = df["post_texto"].apply(extraer_direcciones)
df["barrios_detectados"] = df["post_texto"].apply(extraer_barrios)

productos = df["post_texto"].apply(extraer_productos)
df["categoria_producto"] = productos.apply(lambda x: x[0])
df["productos_keywords"] = productos.apply(lambda x: x[1])

df["tiene_nombre_estimado"] = df["nombre_negocio_estimado"].apply(lambda x: "Si" if x else "No")
df["tiene_direccion"] = df["direcciones_detectadas"].apply(lambda x: "Si" if x else "No")
df["tiene_categoria"] = df["categoria_producto"].apply(lambda x: "Si" if x else "No")

df["requiere_revision_manual"] = df.apply(
    lambda row: "Si" if row["tiene_nombre_estimado"] == "No" or row["tiene_direccion"] == "No" else "No",
    axis=1
)

df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

print("Proceso terminado.")
print(f"Posts totales: {len(df)}")
print(f"Con nombre estimado: {(df['tiene_nombre_estimado'] == 'Si').sum()}")
print(f"Con categoría/producto: {(df['tiene_categoria'] == 'Si').sum()}")
print(f"Con dirección: {(df['tiene_direccion'] == 'Si').sum()}")
print(f"Archivo guardado: {OUTPUT_CSV}")