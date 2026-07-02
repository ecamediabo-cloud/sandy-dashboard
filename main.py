from fastapi import FastAPI, Request, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
import json
import os
import io
import re
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import config

# ── session simple con cookie ──────────────────────────────────────────────
from itsdangerous import URLSafeTimedSerializer, BadSignature
signer = URLSafeTimedSerializer(config.SECRET_KEY)

def crear_token(usuario: str) -> str:
    return signer.dumps(usuario)

def verificar_token(token: str) -> Optional[str]:
    try:
        return signer.loads(token, max_age=86400 * 7)
    except BadSignature:
        return None

def get_usuario(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        return None
    return verificar_token(token)

def require_auth(request: Request) -> str:
    usuario = get_usuario(request)
    if not usuario:
        raise HTTPException(status_code=401, detail="No autenticado")
    return usuario

# ── app ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Sandy Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

os.makedirs(config.CARPETA_DATOS, exist_ok=True)

# ── utilidades de datos ────────────────────────────────────────────────────
CACHE_FILE = os.path.join(config.CARPETA_DATOS, "leads_cache.pkl")

def limpiar_telefono(telefono) -> Optional[str]:
    try:
        if pd.isna(telefono) or telefono is None:
            return None
        t = str(telefono).strip()
        if not t:
            return None
        for prefix in ['p:+', 'p:']:
            if t.startswith(prefix):
                t = t[len(prefix):]
        t = re.sub(r'[^\d]', '', t)
        if t.startswith('52') and len(t) > 12:
            t = t[2:]
        if not t.startswith('52') and len(t) == 10:
            t = '52' + t
        return t if len(t) >= 10 else None
    except Exception:
        return None

def obtener_proyecto_del_nombre(nombre_archivo: str) -> str:
    nombre_upper = nombre_archivo.upper()
    for key, value in config.PROYECTOS_MAPPING:
        if key in nombre_upper:
            return value
    nombre_limpio = nombre_archivo.replace('.csv', '').replace('.xlsx', '').replace('_Leads', '').replace('_', ' ').strip()
    return nombre_limpio if nombre_limpio else "Desconocido"

def guardar_cache(df: pd.DataFrame):
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump({'df': df, 'timestamp': datetime.now()}, f)
    except Exception:
        pass

def cargar_cache() -> tuple:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                data = pickle.load(f)
                return data.get('df', pd.DataFrame()), data.get('timestamp')
    except Exception:
        pass
    return pd.DataFrame(), None

def cargar_archivos_locales() -> pd.DataFrame:
    directorio = Path(config.CARPETA_DATOS)
    archivos = list(directorio.glob("*.csv")) + list(directorio.glob("*.xlsx")) + list(directorio.glob("*.xls"))
    df_consolidado = pd.DataFrame()

    archivos_leidos = 0
    archivos_fallidos = []

    for archivo in sorted(archivos):
        df = None
        try:
            # Intentar leer .xlsx o .xls
            if archivo.suffix.lower() in ['.xlsx', '.xls']:
                try:
                    df = pd.read_excel(archivo, engine='openpyxl')
                    print(f"✅ Leído Excel (openpyxl): {archivo.name} - {len(df)} rows")
                except Exception as e_xlsx:
                    # Si falla openpyxl, intentar con xlrd
                    try:
                        df = pd.read_excel(archivo, engine='xlrd')
                        print(f"✅ Leído Excel (xlrd): {archivo.name} - {len(df)} rows")
                    except Exception as e_xlrd:
                        print(f"❌ Error leyendo Excel {archivo.name}: openpyxl={str(e_xlsx)[:50]}, xlrd={str(e_xlrd)[:50]}")
                        archivos_fallidos.append(archivo.name)
                        continue
            else:
                # CSV: intentar múltiples encodings y separadores
                leido = False
                for sep in ['\t', ',', ';']:
                    if leido:
                        break
                    for enc in ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-16']:
                        try:
                            df = pd.read_csv(archivo, sep=sep, encoding=enc, on_bad_lines='skip')
                            if not df.empty:
                                print(f"✅ Leído CSV: {archivo.name} (sep='{sep}', enc='{enc}') - {len(df)} rows")
                                leido = True
                                break
                        except Exception:
                            continue

                if not leido or df is None or df.empty:
                    print(f"⚠️ Archivo CSV no leído: {archivo.name}")
                    archivos_fallidos.append(archivo.name)
                    continue

            if df is None or df.empty:
                print(f"⚠️ Archivo vacío después de procesar: {archivo.name}")
                archivos_fallidos.append(archivo.name)
                continue

            archivos_leidos += 1
        except Exception as e:
            print(f"❌ Error procesando {archivo.name}: {str(e)[:100]}")
            archivos_fallidos.append(archivo.name)
            continue

        nombre_proyecto = obtener_proyecto_del_nombre(archivo.name)
        df['Proyecto'] = nombre_proyecto

        mapeo = {}
        tel_mapeado = False
        for col in df.columns:
            cl = col.strip().lower()
            if 'full name' in cl or 'nombre' in cl:
                mapeo[col] = 'Nombre completo'
            elif not tel_mapeado and any(x in cl for x in ['phone', 'telefono', 'teléfono']):
                mapeo[col] = 'Teléfono'
                tel_mapeado = True
            elif any(x in cl for x in ['correo', 'email']):
                mapeo[col] = 'Correo'
            elif 'presupuesto' in cl:
                mapeo[col] = 'Presupuesto'
            elif any(x in cl for x in ['comprar', 'crédito', 'credito']):
                mapeo[col] = 'Tipo de Crédito'
            elif any(x in cl for x in ['ad_name', 'anuncio']):
                mapeo[col] = 'Anuncio'
            elif any(x in cl for x in ['created_time', 'fecha']):
                mapeo[col] = 'Fecha de Creación'
            elif 'platform' in cl:
                mapeo[col] = 'Plataforma'
            elif 'campaign' in cl or 'campaña' in cl:
                mapeo[col] = 'Campaña'
            elif 'adset' in cl or 'conjunto' in cl:
                mapeo[col] = 'Conjunto de Anuncios'
            elif 'zona' in cl:
                mapeo[col] = 'Zona'

        df = df.rename(columns=mapeo)
        columnas_ok = [c for c in df.columns if c in [
            'Nombre completo', 'Teléfono', 'Correo', 'Presupuesto',
            'Tipo de Crédito', 'Anuncio', 'Fecha de Creación', 'Proyecto',
            'Plataforma', 'Campaña', 'Conjunto de Anuncios', 'Zona'
        ]]
        df = df[columnas_ok].copy()

        if 'Teléfono' in df.columns:
            df['Teléfono'] = df['Teléfono'].apply(limpiar_telefono)

        df_consolidado = df if df_consolidado.empty else pd.concat([df_consolidado, df], ignore_index=True, sort=False)

    return df_consolidado

def obtener_df_leads(forzar=False) -> pd.DataFrame:
    if not forzar:
        df_cache, _ = cargar_cache()
        if not df_cache.empty:
            return df_cache

    df_local = cargar_archivos_locales()

    df_meta = pd.DataFrame()
    try:
        import meta_ads
        token = meta_ads.obtener_token_meta()
        if token:
            df_meta = meta_ads.obtener_todos_leads_meta_sync(token)
    except Exception:
        pass

    if not df_meta.empty and not df_local.empty:
        df_final = pd.concat([df_meta, df_local], ignore_index=True, sort=False)
        if 'Teléfono' in df_final.columns and 'Fecha de Creación' in df_final.columns:
            df_final = df_final.drop_duplicates(subset=['Teléfono', 'Fecha de Creación'], keep='first')
    elif not df_meta.empty:
        df_final = df_meta
    elif not df_local.empty:
        df_final = df_local
    else:
        df_final = pd.DataFrame()

    if not df_final.empty:
        df_final = df_final.reset_index(drop=True)
        guardar_cache(df_final)

    return df_final

def df_a_dict(df: pd.DataFrame) -> list:
    df2 = df.copy()
    for col in df2.columns:
        if df2[col].dtype == 'object':
            df2[col] = df2[col].fillna('').astype(str)
        else:
            df2[col] = df2[col].where(pd.notna(df2[col]), None)
            try:
                df2[col] = df2[col].astype(str).replace('None', '')
            except Exception:
                pass
    return df2.to_dict(orient='records')

# ── rutas HTML ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    usuario = get_usuario(request)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "autenticado": usuario is not None,
        "usuario": usuario or "",
        "cliente_nombre": config.CLIENTE_NOMBRE,
        "cliente_descripcion": config.CLIENTE_DESCRIPCION,
    })

# ── auth ───────────────────────────────────────────────────────────────────
@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    usuario = data.get("usuario", "")
    contrasena = data.get("contrasena", "")
    if usuario in config.USUARIOS and config.USUARIOS[usuario] == contrasena:
        token = crear_token(usuario)
        resp = JSONResponse({"ok": True, "usuario": usuario, "es_admin": usuario == "admin"})
        resp.set_cookie("session", token, httponly=True, max_age=86400 * 7, samesite="lax")
        return resp
    return JSONResponse({"ok": False, "error": "Usuario o contraseña incorrectos"}, status_code=401)

@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp

@app.get("/api/me")
async def me(request: Request):
    usuario = get_usuario(request)
    if not usuario:
        return JSONResponse({"autenticado": False})
    return JSONResponse({"autenticado": True, "usuario": usuario, "es_admin": usuario == "admin"})

# ── leads ──────────────────────────────────────────────────────────────────
@app.get("/api/leads")
async def get_leads(
    request: Request,
    proyecto: str = Query(None),
    presupuesto: str = Query(None),
    credito: str = Query(None),
    anuncio: str = Query(None),
    campaña: str = Query(None),
    conjunto: str = Query(None),
    zona: str = Query(None),
    plataforma: str = Query(None),
    fecha_inicio: str = Query(None),
    fecha_fin: str = Query(None),
    busqueda: str = Query(None),
    forzar: bool = Query(False),
):
    require_auth(request)
    df = obtener_df_leads(forzar=forzar)
    print(f"📊 GET_LEADS: DataFrame inicial tiene {len(df)} rows, columnas: {list(df.columns) if not df.empty else 'VACÍO'}")

    if df.empty:
        print("❌ GET_LEADS: DataFrame vacío!")
        return JSONResponse({"leads": [], "total": 0, "filtros": {}, "ultima_actualizacion": None})

    # filtros
    if proyecto and proyecto != "Todos":
        proyectos_lista = proyecto.split("|")
        if 'Proyecto' in df.columns:
            df = df[df['Proyecto'].isin(proyectos_lista)]

    if presupuesto and presupuesto != "Todos":
        pres_lista = presupuesto.split("|")
        if 'Presupuesto' in df.columns:
            df = df[df['Presupuesto'].isin(pres_lista)]

    if credito and credito != "Todos":
        cred_lista = credito.split("|")
        if 'Tipo de Crédito' in df.columns:
            df = df[df['Tipo de Crédito'].isin(cred_lista)]

    if anuncio and anuncio != "Todos":
        anuncio_lista = anuncio.split("|")
        if 'Anuncio' in df.columns:
            df = df[df['Anuncio'].isin(anuncio_lista)]

    if campaña and campaña != "Todos":
        camp_lista = campaña.split("|")
        if 'Campaña' in df.columns:
            df = df[df['Campaña'].isin(camp_lista)]

    if conjunto and conjunto != "Todos":
        conj_lista = conjunto.split("|")
        if 'Conjunto de Anuncios' in df.columns:
            df = df[df['Conjunto de Anuncios'].isin(conj_lista)]

    if zona and zona != "Todas":
        zona_lista = zona.split("|")
        if 'Zona' in df.columns:
            df = df[df['Zona'].isin(zona_lista)]

    if plataforma and plataforma != "Todos":
        plat_lista = plataforma.split("|")
        if 'Plataforma' in df.columns:
            df = df[df['Plataforma'].isin(plat_lista)]

    if busqueda and 'Nombre completo' in df.columns:
        df = df[df['Nombre completo'].str.contains(busqueda, case=False, na=False)]

    if fecha_inicio and fecha_fin and 'Fecha de Creación' in df.columns:
        try:
            fechas = pd.to_datetime(df['Fecha de Creación'], errors='coerce', utc=True)
            fi = pd.to_datetime(fecha_inicio).tz_localize('UTC')
            ff = pd.to_datetime(fecha_fin).tz_localize('UTC') + timedelta(days=1)
            df = df[(fechas >= fi) & (fechas <= ff)]
        except Exception:
            pass

    _, ts = cargar_cache()
    ts_str = ts.strftime("%d/%m/%Y %H:%M") if ts else None

    # DEBUG: Convertir a dict antes de retornar
    try:
        leads_dict = df_a_dict(df)
        print(f"✅ GET_LEADS: Convertido a dict, {len(leads_dict)} records")
        if leads_dict and len(leads_dict) > 0:
            print(f"  Primer lead: {str(leads_dict[0])[:200]}")
    except Exception as e:
        print(f"❌ GET_LEADS: Error en df_a_dict: {str(e)}")
        leads_dict = []

    return JSONResponse({
        "leads": leads_dict,
        "total": len(df),
        "ultima_actualizacion": ts_str,
    })

@app.get("/api/filtros")
async def get_filtros(request: Request):
    require_auth(request)
    df = obtener_df_leads()
    if df.empty:
        return JSONResponse({"proyectos": [], "presupuestos": [], "creditos": [],
                             "anuncios": [], "campanas": [], "conjuntos": [],
                             "zonas": [], "plataformas": []})

    def unicos(col):
        if col not in df.columns:
            return []
        return sorted([str(v) for v in df[col].dropna().unique() if str(v).strip()])

    return JSONResponse({
        "proyectos": unicos("Proyecto"),
        "presupuestos": unicos("Presupuesto"),
        "creditos": unicos("Tipo de Crédito"),
        "anuncios": unicos("Anuncio"),
        "campanas": unicos("Campaña"),
        "conjuntos": unicos("Conjunto de Anuncios"),
        "zonas": unicos("Zona"),
        "plataformas": unicos("Plataforma"),
    })

@app.get("/api/stats")
async def get_stats(request: Request):
    require_auth(request)
    df = obtener_df_leads()
    if df.empty:
        return JSONResponse({"total": 0, "hoy": 0, "semana": 0, "proyectos": 0,
                             "por_proyecto": [], "por_presupuesto": [], "por_credito": [], "por_plataforma": []})

    hoy = datetime.now().date()
    semana = (datetime.now() - timedelta(days=7)).date()

    leads_hoy = 0
    leads_semana = 0
    if 'Fecha de Creación' in df.columns:
        try:
            fechas = pd.to_datetime(df['Fecha de Creación'], errors='coerce').dt.date
            leads_hoy = int((fechas == hoy).sum())
            leads_semana = int((fechas >= semana).sum())
        except Exception:
            pass

    def top_valores(col, n=10):
        if col not in df.columns:
            return []
        vc = df[col].value_counts().head(n)
        return [{"label": str(k), "value": int(v)} for k, v in vc.items()]

    return JSONResponse({
        "total": len(df),
        "hoy": leads_hoy,
        "semana": leads_semana,
        "proyectos": int(df['Proyecto'].nunique()) if 'Proyecto' in df.columns else 0,
        "por_proyecto": top_valores("Proyecto"),
        "por_presupuesto": top_valores("Presupuesto"),
        "por_credito": top_valores("Tipo de Crédito"),
        "por_plataforma": top_valores("Plataforma"),
    })

# ── upload ─────────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_file(request: Request, files: List[UploadFile] = File(...)):
    usuario = require_auth(request)
    if usuario != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden subir archivos")

    resultados = []
    for archivo in files:
        try:
            # Validar extensión (flexible con mayúsculas)
            nombre_original = archivo.filename or ""
            ext = Path(nombre_original).suffix.lower().strip()

            # Aceptar .csv, .xlsx, .xls (incluso con espacios o caracteres raros)
            extensiones_validas = ['.csv', '.xlsx', '.xls']
            if ext not in extensiones_validas:
                resultados.append({
                    "archivo": nombre_original,
                    "ok": False,
                    "error": f"Extensión '{ext}' no válida. Usa CSV o Excel"
                })
                continue

            # Limpiar nombre: reemplazar caracteres especiales
            nombre_limpio = re.sub(r'[^\w\s\-\.]', '', nombre_original)
            nombre_limpio = re.sub(r'\s+', '_', nombre_limpio)  # espacios → guiones bajos
            nombre_limpio = nombre_limpio[:200]  # limitar longitud

            ruta = os.path.join(config.CARPETA_DATOS, nombre_limpio)
            contenido = await archivo.read()

            if not contenido:
                resultados.append({
                    "archivo": nombre_original,
                    "ok": False,
                    "error": "Archivo vacío"
                })
                continue

            with open(ruta, 'wb') as f:
                f.write(contenido)

            resultados.append({
                "archivo": nombre_original,
                "ok": True,
                "guardado_como": nombre_limpio
            })
        except Exception as e:
            resultados.append({
                "archivo": archivo.filename or "desconocido",
                "ok": False,
                "error": str(e)[:80]
            })

    # limpiar cache para que recargue
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)

    return JSONResponse({"resultados": resultados})

# ── exportaciones ──────────────────────────────────────────────────────────
def construir_df_filtrado(request: Request, params: dict) -> pd.DataFrame:
    return obtener_df_leads()

def _nombre_desde_filtros(filtros_json: str, ext: str) -> str:
    try:
        f = json.loads(filtros_json) if filtros_json else {}
        nombre_base = f.get('nombre_archivo', '').strip()
        if nombre_base:
            nombre_base = re.sub(r'[^\w\-]', '_', nombre_base)[:80]
            return f"{nombre_base}.{ext}"
    except Exception:
        pass
    return f"Leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

@app.get("/api/export/excel")
async def export_excel(request: Request, filtros: str = Query("")):
    require_auth(request)
    df = _df_desde_filtros(filtros)
    output = io.BytesIO()
    df.to_excel(output, sheet_name='Leads', index=False, engine='openpyxl')
    output.seek(0)
    nombre = _nombre_desde_filtros(filtros, 'xlsx')
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )

@app.get("/api/export/csv")
async def export_csv(request: Request, filtros: str = Query("")):
    require_auth(request)
    df = _df_desde_filtros(filtros)
    output = io.StringIO()
    df.to_csv(output, index=False)
    nombre = _nombre_desde_filtros(filtros, 'csv')
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )

@app.get("/api/export/pdf")
async def export_pdf(request: Request, filtros: str = Query("")):
    require_auth(request)
    df = _df_desde_filtros(filtros)
    pdf_bytes = generar_pdf(df)
    nombre = _nombre_desde_filtros(filtros, 'pdf')
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )

@app.get("/api/export/html")
async def export_html(request: Request, filtros: str = Query("")):
    require_auth(request)
    df = _df_desde_filtros(filtros)
    html = generar_html_reporte(df)
    nombre = _nombre_desde_filtros(filtros, 'html')
    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )

def _df_desde_filtros(filtros_json: str) -> pd.DataFrame:
    df = obtener_df_leads()
    if not filtros_json or df.empty:
        return df
    try:
        f = json.loads(filtros_json)

        # Filtros por columna
        for col, key in [('Proyecto','proyecto'), ('Presupuesto','presupuesto'),
                         ('Tipo de Crédito','credito'), ('Anuncio','anuncio'),
                         ('Campaña','campana'), ('Conjunto de Anuncios','conjunto'),
                         ('Zona','zona'), ('Plataforma','plataforma')]:
            val = f.get(key)
            if val and val not in ["Todos", "Todas"] and col in df.columns:
                df = df[df[col].isin(val.split("|"))]

        # Búsqueda por nombre
        busqueda = f.get('busqueda', '')
        if busqueda and 'Nombre completo' in df.columns:
            df = df[df['Nombre completo'].str.contains(busqueda, case=False, na=False)]

        # Filtro por fechas
        fecha_inicio = f.get('fecha_inicio', '')
        fecha_fin = f.get('fecha_fin', '')
        if fecha_inicio and fecha_fin and 'Fecha de Creación' in df.columns:
            try:
                fechas = pd.to_datetime(df['Fecha de Creación'], errors='coerce', utc=True)
                fi = pd.to_datetime(fecha_inicio).tz_localize('UTC')
                ff = pd.to_datetime(fecha_fin).tz_localize('UTC') + timedelta(days=1)
                df = df[(fechas >= fi) & (fechas <= ff)]
            except Exception:
                pass

    except Exception:
        pass
    return df

# ── contactos ──────────────────────────────────────────────────────────────
HISTORIAL_FILE = "historial_contactos.json"

@app.get("/api/contactos")
async def get_contactos(request: Request):
    require_auth(request)
    if not os.path.exists(HISTORIAL_FILE):
        return JSONResponse({"contactos": []})
    with open(HISTORIAL_FILE, 'r', encoding='utf-8') as f:
        return JSONResponse({"contactos": json.load(f)})

@app.post("/api/contactos")
async def save_contacto(request: Request):
    require_auth(request)
    data = await request.json()
    historial = []
    if os.path.exists(HISTORIAL_FILE):
        with open(HISTORIAL_FILE, 'r', encoding='utf-8') as f:
            historial = json.load(f)
    historial.append({**data, "fecha": datetime.now().isoformat()})
    with open(HISTORIAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
    return JSONResponse({"ok": True})

# ── meta ads ───────────────────────────────────────────────────────────────
@app.get("/api/meta/status")
async def meta_status(request: Request):
    require_auth(request)
    try:
        import meta_ads
        token = meta_ads.obtener_token_meta()
        return JSONResponse({"conectado": token is not None})
    except Exception:
        return JSONResponse({"conectado": False})

@app.post("/api/meta/token")
async def meta_guardar_token(request: Request):
    usuario = require_auth(request)
    if usuario != "admin":
        raise HTTPException(status_code=403)
    data = await request.json()
    token = data.get("token", "").strip()
    ad_account = data.get("ad_account", "").strip()
    if not token:
        return JSONResponse({"ok": False, "error": "Token vacío"}, status_code=400)
    try:
        import meta_ads
        meta_ads.guardar_token_meta(token, ad_account)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/meta/sync")
async def meta_sync(request: Request):
    usuario = require_auth(request)
    if usuario != "admin":
        raise HTTPException(status_code=403)
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    try:
        df = obtener_df_leads(forzar=True)
        return JSONResponse({"ok": True, "total": len(df)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ── generadores de reporte ─────────────────────────────────────────────────
def generar_html_reporte(df: pd.DataFrame) -> str:
    filas = ""
    for _, row in df.iterrows():
        nombre = str(row.get('Nombre completo', ''))
        telefono = str(row.get('Teléfono', ''))
        correo = str(row.get('Correo', ''))
        presupuesto = str(row.get('Presupuesto', ''))
        credito = str(row.get('Tipo de Crédito', ''))
        proyecto = str(row.get('Proyecto', ''))
        fecha = str(row.get('Fecha de Creación', ''))

        msg = f"Hola {nombre}! Vi tu interés en {proyecto}. Presupuesto: {presupuesto}, Crédito: {credito}. ¿Te comparto modelos disponibles?"
        msg_enc = msg.replace(' ', '%20')
        if telefono and telefono not in ['', 'None', 'nan']:
            btn = f'<a href="https://wa.me/{telefono}?text={msg_enc}" target="_blank" class="btn-wa">💬 WhatsApp</a>'
        else:
            btn = '<span class="no-tel">Sin teléfono</span>'

        filas += f"""<tr>
            <td class="nombre">{nombre}</td>
            <td class="tel">{telefono}</td>
            <td class="email">{correo}</td>
            <td>{presupuesto}</td>
            <td>{credito}</td>
            <td>{proyecto}</td>
            <td>{fecha[:10] if len(fecha) >= 10 else fecha}</td>
            <td>{btn}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte de Leads · Sandy Dashboard</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'Segoe UI',sans-serif;background:#0a0a0f;color:#fff;padding:24px}}
  .wrap{{max-width:1400px;margin:0 auto;background:#111118;border-radius:16px;overflow:hidden;box-shadow:0 24px 64px rgba(0,0,0,.6)}}
  .hdr{{background:linear-gradient(135deg,#C9A961,#a07c3a);padding:36px 40px;display:flex;justify-content:space-between;align-items:center}}
  .hdr h1{{font-size:24px;font-weight:700;color:#fff}}
  .hdr p{{font-size:13px;color:rgba(255,255,255,.8);margin-top:4px}}
  .meta-bar{{display:grid;grid-template-columns:repeat(4,1fr);background:#1a1a24;border-bottom:1px solid #C9A961}}
  .meta-item{{padding:20px 24px;text-align:center;border-right:1px solid #252530}}
  .meta-label{{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px}}
  .meta-val{{font-size:20px;font-weight:700;color:#C9A961;margin-top:4px}}
  .body{{padding:32px}}
  table{{width:100%;border-collapse:collapse}}
  thead tr{{background:#C9A961}}
  th{{padding:13px 14px;text-align:left;font-size:12px;font-weight:600;color:#fff;text-transform:uppercase;letter-spacing:.4px}}
  td{{padding:13px 14px;border-bottom:1px solid #1e1e2a;font-size:13px;color:#d0d0e0}}
  tr:hover td{{background:#16161f}}
  .nombre{{font-weight:600;color:#fff}}
  .tel{{font-family:monospace;color:#4db8ff}}
  .email{{color:#888;font-size:12px}}
  .btn-wa{{background:linear-gradient(135deg,#25D366,#1aab52);color:#fff;border:none;padding:8px 16px;border-radius:8px;font-weight:600;font-size:12px;cursor:pointer;text-decoration:none;display:inline-block}}
  .btn-wa:hover{{opacity:.9}}
  .no-tel{{color:#555;font-size:12px}}
  .footer{{background:#0d0d14;padding:20px 40px;text-align:center;color:#555;font-size:12px;border-top:1px solid #1e1e2a}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div><h1>🏠 REPORTE DE LEADS INMOBILIARIOS</h1><p>Sandy Dashboard · ECA MEDIA BO</p></div>
    <div style="text-align:right"><p style="color:rgba(255,255,255,.7);font-size:13px">Generado el</p><p style="font-size:18px;font-weight:700">{datetime.now().strftime('%d/%m/%Y %H:%M')}</p></div>
  </div>
  <div class="meta-bar">
    <div class="meta-item"><div class="meta-label">Total de Leads</div><div class="meta-val">{len(df)}</div></div>
    <div class="meta-item"><div class="meta-label">Proyectos</div><div class="meta-val">{df['Proyecto'].nunique() if 'Proyecto' in df.columns else '-'}</div></div>
    <div class="meta-item"><div class="meta-label">Con teléfono</div><div class="meta-val">{int(df['Teléfono'].notna().sum()) if 'Teléfono' in df.columns else '-'}</div></div>
    <div class="meta-item"><div class="meta-label">Fecha generación</div><div class="meta-val">{datetime.now().strftime('%d/%m/%Y')}</div></div>
  </div>
  <div class="body">
    <table>
      <thead><tr><th>Nombre</th><th>Teléfono</th><th>Correo</th><th>Presupuesto</th><th>Crédito</th><th>Proyecto</th><th>Fecha</th><th>Contacto</th></tr></thead>
      <tbody>{filas}</tbody>
    </table>
  </div>
  <div class="footer">Sandy Dashboard v2.0 · Desarrollado por ECA MEDIA BO · © 2026</div>
</div>
</body>
</html>"""

def generar_pdf(df: pd.DataFrame) -> bytes:
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                            topMargin=0.3*inch, bottomMargin=0.3*inch,
                            leftMargin=0.3*inch, rightMargin=0.3*inch)
    elementos = []
    styles = getSampleStyleSheet()
    gold = colors.HexColor('#C9A961')
    dark = colors.HexColor('#0a0a0f')

    hdr_data = [['ECA MEDIA BO · Sandy Dashboard', f'REPORTE DE LEADS  |  {datetime.now().strftime("%d/%m/%Y %H:%M")}  |  Total: {len(df)}']]
    hdr_tbl = Table(hdr_data, colWidths=[3.5*inch, 6.5*inch])
    hdr_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), gold),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
    ]))
    elementos.append(hdr_tbl)
    elementos.append(Spacer(1, 0.2*inch))

    datos = [['Nombre', 'Teléfono', 'Correo', 'Presupuesto', 'Crédito', 'Conjunto/Anuncio', 'Zona', 'Fecha']]
    for _, row in df.iterrows():
        conjunto = str(row.get('Conjunto de Anuncios', ''))[:24].strip()
        if not conjunto or conjunto == 'nan':
            conjunto = str(row.get('Anuncio', ''))[:24].strip()

        datos.append([
            str(row.get('Nombre completo', ''))[:30],
            str(row.get('Teléfono', ''))[:15],
            str(row.get('Correo', ''))[:32],
            str(row.get('Presupuesto', ''))[:22],
            str(row.get('Tipo de Crédito', ''))[:22],
            conjunto,
            str(row.get('Zona', ''))[:14],
            str(row.get('Fecha de Creación', ''))[:10],
        ])

    tabla = Table(datos, colWidths=[1.7*inch, 1.0*inch, 1.9*inch, 1.4*inch, 1.4*inch, 1.5*inch, 0.9*inch, 0.8*inch])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), gold),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 7),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('ALIGN', (0,1), (-1,-1), 'LEFT'),
        ('FONTSIZE', (0,1), (-1,-1), 6.5),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f9f9f9'), colors.white]),
        ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#222')),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#ddd')),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 0.2*inch))

    footer_style = ParagraphStyle('f', parent=styles['Normal'], fontSize=7,
                                  textColor=colors.HexColor('#888'), alignment=TA_CENTER)
    elementos.append(Paragraph('Sandy Dashboard v2.0 · ECA MEDIA BO · © 2026 · ecamediabo.com', footer_style))

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()
