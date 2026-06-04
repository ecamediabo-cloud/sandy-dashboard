"""
Meta Ads Integration — Sandy Dashboard v2
Versión síncrona para FastAPI
"""

import json
import os
import time
import pandas as pd
from datetime import datetime
import config

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

TOKEN_FILE = os.path.join(config.CARPETA_DATOS, "meta_token.json")


def obtener_token_meta() -> str | None:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return data.get('access_token')
    except Exception:
        pass
    return None


def obtener_ad_account() -> str | None:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return data.get('ad_account_id')
    except Exception:
        pass
    return None


def guardar_token_meta(token: str, ad_account_id: str = ""):
    os.makedirs(config.CARPETA_DATOS, exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'access_token': token,
            'ad_account_id': ad_account_id,
            'saved_at': str(datetime.now())
        }, f)


def _get_paginado(url: str, headers: dict, params: dict, max_paginas: int = 2000) -> list:
    all_data = []
    next_url = url
    next_params = params.copy()
    pagina = 0

    while next_url and pagina < max_paginas:
        try:
            response = requests.get(next_url, headers=headers, params=next_params, timeout=60)
            reintentos = 0
            while response.status_code != 200 and reintentos < 3:
                time.sleep(2)
                response = requests.get(next_url, headers=headers, params=next_params, timeout=60)
                reintentos += 1

            if response.status_code != 200:
                break

            data = response.json()
            all_data.extend(data.get('data', []))
            paging = data.get('paging', {})
            next_url = paging.get('next')
            next_params = {}
            pagina += 1
            if not next_url:
                break
        except Exception:
            break

    return all_data


def _parsear_field_data(field_data: list, lead_dict: dict) -> dict:
    first_name = ''
    last_name = ''
    posibles_nombres = []

    for field in field_data:
        name_raw = field.get('name', '')
        name_lc = name_raw.lower().strip()
        values = field.get('values', [])
        val = str(values[0]).strip() if values else ''
        if not val:
            continue

        if name_lc in ['full_name', 'fullname', 'nombre_completo', 'nombre completo', 'name', 'nombre']:
            lead_dict['nombre_completo'] = val
        elif name_lc in ['first_name', 'firstname', 'primer_nombre']:
            first_name = val
        elif name_lc in ['last_name', 'lastname', 'apellido', 'apellidos', 'surname']:
            last_name = (last_name + ' ' + val).strip() if last_name else val
        elif any(x in name_lc for x in ['phone', 'telefono', 'teléfono', 'whatsapp', 'celular']):
            lead_dict['telefono'] = val
        elif any(x in name_lc for x in ['email', 'correo', 'mail']):
            lead_dict['correo'] = val
        elif any(x in name_lc for x in ['budget', 'presupuesto', 'precio', 'rango']):
            lead_dict['presupuesto'] = val
        elif any(x in name_lc for x in ['credit', 'credito', 'crédito', 'financiamiento', 'compra']):
            lead_dict['tipo_credito'] = val
        elif any(x in name_lc for x in ['zona', 'ubicacion', 'ubicación', 'area', 'ciudad', 'lugar']):
            lead_dict['zona'] = val
        else:
            if ('@' not in val and not val.replace(' ', '').replace('-', '').isdigit()
                    and val.lower() not in ['si', 'no', 'yes', 'true', 'false']):
                posibles_nombres.append(val)

    if (first_name or last_name) and not lead_dict.get('nombre_completo'):
        lead_dict['nombre_completo'] = (first_name + ' ' + last_name).strip()

    if not lead_dict.get('nombre_completo') and posibles_nombres:
        lead_dict['nombre_completo'] = posibles_nombres[0]

    return lead_dict


def obtener_todos_leads_meta_sync(token: str) -> pd.DataFrame:
    if not REQUESTS_OK:
        return pd.DataFrame()

    ad_account_id = obtener_ad_account()
    if not ad_account_id:
        return pd.DataFrame()

    if not ad_account_id.startswith('act_'):
        ad_account_id = f"act_{ad_account_id}"

    headers = {'Authorization': f'Bearer {token}'}
    all_leads = []
    leads_ids_vistos = set()

    # Obtener páginas
    pages = []
    try:
        resp = requests.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            headers=headers,
            params={'fields': 'id,name,access_token', 'limit': 100},
            timeout=30
        )
        if resp.status_code == 200:
            pages = resp.json().get('data', [])
    except Exception:
        pass

    # Obtener formularios desde páginas
    formularios = {}
    for page in pages:
        page_token = page.get('access_token', token)
        page_headers = {'Authorization': f'Bearer {page_token}'}
        forms = _get_paginado(
            f"https://graph.facebook.com/v20.0/{page['id']}/leadgen_forms",
            page_headers,
            {'fields': 'id,name,status', 'limit': 200}
        )
        for form in forms:
            fid = form['id']
            if fid not in formularios:
                formularios[fid] = (form.get('name', 'Sin nombre'), page_token)

    # Formularios desde ad account
    try:
        ad_forms = _get_paginado(
            f"https://graph.facebook.com/v20.0/{ad_account_id}/leadgen_forms",
            headers,
            {'fields': 'id,name', 'limit': 200}
        )
        for form in ad_forms:
            fid = form['id']
            if fid not in formularios:
                pt = pages[0].get('access_token', token) if pages else token
                formularios[fid] = (form.get('name', 'Sin nombre'), pt)
    except Exception:
        pass

    # Obtener leads de cada formulario
    tokens_disponibles = [p.get('access_token', token) for p in pages] + [token]
    tokens_disponibles = list(dict.fromkeys(tokens_disponibles))

    for form_id, (form_name, primary_token) in formularios.items():
        tokens_a_probar = [primary_token] + [t for t in tokens_disponibles if t != primary_token]
        leads_data = []

        for try_token in tokens_a_probar:
            try_headers = {'Authorization': f'Bearer {try_token}'}
            leads_url = f"https://graph.facebook.com/v20.0/{form_id}/leads"
            leads_params = {
                'fields': 'id,created_time,field_data,platform,ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name',
                'limit': 500
            }
            try:
                test = requests.get(leads_url, headers=try_headers, params=leads_params, timeout=30)
                if test.status_code == 200:
                    leads_data = _get_paginado(leads_url, try_headers, leads_params)
                    break
            except Exception:
                continue

        for lead in leads_data:
            lead_id = lead.get('id')
            if lead_id and lead_id in leads_ids_vistos:
                continue
            if lead_id:
                leads_ids_vistos.add(lead_id)

            lead_dict = {
                'campana': lead.get('campaign_name') or form_name,
                'conjunto_anuncios': lead.get('adset_name', ''),
                'anuncio': lead.get('ad_name') or form_name,
                'proyecto': lead.get('campaign_name') or form_name,
                'nombre_completo': '',
                'telefono': '',
                'correo': '',
                'presupuesto': '',
                'tipo_credito': '',
                'zona': '',
                'plataforma': (lead.get('platform') or 'Facebook').capitalize(),
                'fecha_creacion': lead.get('created_time', ''),
            }
            lead_dict = _parsear_field_data(lead.get('field_data', []), lead_dict)
            all_leads.append(lead_dict)

    if not all_leads:
        return pd.DataFrame()

    df = pd.DataFrame(all_leads).rename(columns={
        'campana': 'Campaña',
        'conjunto_anuncios': 'Conjunto de Anuncios',
        'anuncio': 'Anuncio',
        'proyecto': 'Proyecto',
        'nombre_completo': 'Nombre completo',
        'telefono': 'Teléfono',
        'correo': 'Correo',
        'presupuesto': 'Presupuesto',
        'tipo_credito': 'Tipo de Crédito',
        'zona': 'Zona',
        'plataforma': 'Plataforma',
        'fecha_creacion': 'Fecha de Creación',
    })

    return df


def verificar_conexion_meta() -> dict:
    """Verifica token y devuelve info del usuario."""
    if not REQUESTS_OK:
        return {"ok": False, "error": "requests no instalado"}
    token = obtener_token_meta()
    if not token:
        return {"ok": False, "error": "Sin token"}
    try:
        resp = requests.get(
            "https://graph.facebook.com/v20.0/me",
            headers={'Authorization': f'Bearer {token}'},
            params={'fields': 'id,name'},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"ok": True, "nombre": data.get('name'), "id": data.get('id')}
        return {"ok": False, "error": resp.text[:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}
