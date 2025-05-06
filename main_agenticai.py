from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI, OpenAI
from websockets.exceptions import ConnectionClosed

import uvicorn

# for agenai
import duckdb


ENDPOINT = "http://127.0.0.1:39281/v1"
MODEL = "llama3:8b"

client = AsyncOpenAI(
    base_url=ENDPOINT,
    api_key="not-needed"
) 

client2 = OpenAI(
    base_url=ENDPOINT,
    api_key="not-needed"
) 

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
 
@app.get("/", response_class=HTMLResponse)
async def root( request: Request ):
    return RedirectResponse("/static/index.html")

@app.websocket("/init")
async def init( websocket: WebSocket ):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_json()

            await websocket.send_json( { "action": "init_system_response" } )
            response = await plan_messages( data, websocket )
            await websocket.send_json( { "action": "finish_system_response" } )
    except (WebSocketDisconnect, ConnectionClosed):
        print( "Conexión cerrada" )

async def plan_messages( messages, websocket ):
    pmsg = [ 
        { "role": "system", "content": """
        Responde solo 'No' en caso de no ser posible responder con los datos del csv.
        Responde solo 'No' en caso de pedir información de empresas que no sean Lostsys.
        Responde solo la sentencia SQL para la base de datos DuckDB a ejecutar en caso de poder obtener los datos del csv.
        Responde siempre Sin explicación, Sin notas, Sin delimitaciones.
        Disponemos de un csv llamado 'facturas.csv' que contiene estos campos: 'fecha' del tipo VARCHAR usando el formato de fecha 'YYYY-MM-DD', 'cliente' tipo INTEGER que contiene el id de cliente, 'pais' tipo VARCHAR que contiene 'ES' como España y 'UK' como reino unido, 'importe' con el total de la factura. 
        No puedes suponer nada ni usar otros datos que no sean los del csv 'facturas.csv'.
        """ },
        { "role": "user", "content": messages[ -1 ]["content"] }         
    ]

    response = client2.chat.completions.create(
        top_p=0.9,
        temperature=0.9,
        model=MODEL,
        messages=pmsg,
    )

    r = response.choices[0].message.content
    print( r )
    r = clean_sql( r )

    if not r.startswith("No"):
        await websocket.send_json( { "action": "append_system_response", "content": r } )
        await websocket.send_json( { "action": "append_system_response", "content": "\n\n<b>Resultado: </b>" + execute__query( r ) } )

        return

    return await process_messages( messages, websocket )

def execute__query( sql ):
    return str( duckdb.sql( sql ).fetchall() )

def clean_sql( sql ):
    # 2 lines added for deepseek r1
    if sql.find("<|end_of_text|>") != -1: sql = sql[sql.find("<|end_of_text|>")+15:]
    if sql.find("</think>") != -1: sql = sql[sql.find("</think>")+8:]

    sql = sql.strip()

    if sql.startswith("```sql"): sql = sql[6:]
    if sql.startswith("```"): sql = sql[3:]
    if sql.endswith("```"): sql = sql[:len(sql)-3]
    if sql.find("```") != -1: sql = sql[sql.find("```"):]
    sql = sql.replace( "FROM facturas", "FROM './facturas.csv'" )
    sql = sql.replace( "fecha", "CAST(fecha AS VARCHAR)" )
    
    return sql

async def process_messages( messages, websocket ):
    completion_payload = {
        "messages": messages
    }

    response = await client.chat.completions.create(
        top_p=0.9,
        temperature=0.6,
        model=MODEL,
        messages=completion_payload["messages"],
        stream=True
    )

    respStr = ""
    async for chunk in response:
        if (not chunk.choices[0] or
            not chunk.choices[0].delta or
            not chunk.choices[0].delta.content):
          continue

        await websocket.send_json( { "action": "append_system_response", "content": chunk.choices[0].delta.content } )

    return respStr


uvicorn.run(app, host="0.0.0.0", port=8000)