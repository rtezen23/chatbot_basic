from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from websockets.exceptions import ConnectionClosed

import uvicorn

# for rag
import chromadb
import json

# selecting model
ENDPOINT = "http://127.0.0.1:39281/v1"
#MODEL = "phi-3.5:3b-gguf-q4-km"
#MODEL = "deepseek-r1-distill-qwen-14b:14b-gguf-q4-km" too big/slow
# MODEL = "llama3.2:3b-gguf-q4-km"
# MODEL = "tinyllama:1b" too small/basic
MODEL = "mistral:7b"

# ChromaDB logic
client = chromadb.Client()

collection = client.create_collection("tienda-bachi-documents")

collection.add(
    documents=[
        "En tienda Bachi, ofrecemos la venta de productos de bodega y librería al por menor, todo en un solo lugar",
        "En tienda Bachi vendemos productos de primera necesidad como azúcar, leche, arroz, embutidos, además bebidas como agua, gaseosas y refrescos, galletas, dulces, snacks, entre otros",
        "En tienda Bachi vendemos productos escolares, universitarios y de oficina, como cuadernos, lapiceros, colores, plumones, papelógrafos, tijeras, fólderes, pegamento, entre otros",
        "En tienda Bachi también vendemos productos adicionales como hilos, cortauñas, decoraciones, juguetes, pinzas, etc",
        "Para épocas de calor vendemos helados de crema y hielo marca yamboli, donde tenemos el helado de barquillo, bombones, sandwich, vasito personal y familiar, helado con grajeas, entre otros",
        "En días festivos en Perú como día de la madre, día de la bandera, halloween, navidad, y otros, ofrecemos productos especiales acordes al evento, para usarlos en el colegio, trabajo, etc",
        "El horario de atención de tienda Bachi es de Lunes a Sábado de 8am a 10pm y los Domingos de 9am a 9pm, y trabajamos feriados, solo considerar que hay momentos donde cerramos la tienda por algunas horas, pero esto lo informamos en el mismo local y redes sociales",
    ],
    ids=["id1", "id2","id3", "id4","id5", "id6", "id7"]
)

system_prompt = """
Eres un asistente de la tienda Bachi que ayuda a sus clientes con sus dudas generales sobre la tienda. Sigue estas instrucciones:
- Ofrece respuestas cortas y concisas de pocas palabras, si vas a listar cosas o categorías, muéstralo en un formato ordenado y sin dar ejemplos adicionales.
- No ofrezcas consejos, productos o servicios de terceros, todas las respuesta deben centrarse en la tienda bachi cuya, informacion te brindaré a continuación:"""

#### END ChromaDB

client = AsyncOpenAI(
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
            response = await process_messages( data, websocket )
            await websocket.send_json( { "action": "finish_system_response" } )
    except (WebSocketDisconnect, ConnectionClosed):
        print( "Conexión cerrada" )

async def process_messages( messages, websocket ):
    
    results = collection.query(
        query_texts=[messages[-1]['content']] ,
        n_results=2
    )
    
    pmsg = [ { "role": "system", "content": system_prompt + str( results["documents"][0] ) } ]
    print( json.dumps( pmsg + messages, indent=4) )
    
    completion_payload = {
        "messages": pmsg + messages
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