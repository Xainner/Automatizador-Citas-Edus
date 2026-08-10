#!/usr/bin/env python3
"""
EDUS Citas - Login con CAPTCHA resuelto por visión de Hermes.
Flujo completo en una sola sesión de navegador.

El script descarga el CAPTCHA, lo mejora y lo guarda, luego PAUSA
para que Hermes lo lea con visión. Después continúa automáticamente.
"""
import os
import sys
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CEDULA = os.environ.get("EDUS_CEDULA")
CLAVE = os.environ.get("EDUS_CLAVE")
if not CEDULA or not CLAVE:
    print("❌ Error: EDUS_CEDULA y EDUS_CLAVE son requeridos")
    print("   Configura las variables de entorno o crea un archivo .env")
    sys.exit(1)
SERVICIO = os.environ.get("SERVICIO", "1")
ESPECIALIDAD = os.environ.get("ESPECIALIDAD", "1033")
EXCLUIR_FECHAS = [f.strip() for f in os.environ.get("EXCLUIR_FECHAS", "").split(",") if f.strip()]
# Fecha objetivo (DD/MM/AAAA): si se define, solo se consideran cupos de esa fecha exacta
FECHA_OBJETIVO = os.environ.get("FECHA_OBJETIVO", "").strip()

CAPTCHA_DIR = Path(os.environ.get("CAPTCHA_DIR", "/tmp/edus_captcha"))
CAPTCHA_DIR.mkdir(exist_ok=True)

def save_captcha(captcha_bytes):
    """Guardar y mejorar el CAPTCHA."""
    from PIL import Image, ImageEnhance, ImageFilter

    raw = CAPTCHA_DIR / "captcha.png"
    raw.write_bytes(captcha_bytes)

    img = Image.open(raw).convert("L")
    img = ImageEnhance.Contrast(img).enhance(3.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    img = img.filter(ImageFilter.DETAIL)
    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.LANCZOS)

    improved = CAPTCHA_DIR / "captcha_improved.png"
    img.save(improved)
    return str(improved)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-CR",
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        for intento in range(1, 16):
            print(f"\n{'='*50}")
            print(f"[*] Intento #{intento} — Login como {CEDULA}")
            print(f"{'='*50}")

            # ── Cargar login ──
            await page.goto("https://edus.ccss.sa.cr/eduscitasweb/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # ── Descargar CAPTCHA (sin navegar, usar fetch en la página) ──
            captcha_bytes = await page.evaluate("""
                async () => {
                    const resp = await fetch('https://edus.ccss.sa.cr/CitasWebPF/captcha');
                    const buf = await resp.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }
            """)
            captcha_bytes = bytes(captcha_bytes)
            captcha_path = save_captcha(captcha_bytes)
            print(f"  📸 CAPTCHA: {captcha_path}")

            # Esperar a que los elementos del formulario estén listos (usar JS, no CSS selector)
            for _ in range(20):
                ready = await page.evaluate("""
                    () => document.getElementById('formInicioSesion:usuario') !== null
                """)
                if ready:
                    break
                await asyncio.sleep(0.5)
            print("  ✅ Formulario listo")

            # ── PAUSAR para que Hermes lea el CAPTCHA ──
            (CAPTCHA_DIR / "waiting.txt").write_text(captcha_path)
            print(f"  ⏳ Esperando resolución del CAPTCHA...")

            captcha_text = ""
            for wait_sec in range(1, 121):
                await asyncio.sleep(1)
                resolved = CAPTCHA_DIR / "resolved.txt"
                if resolved.exists():
                    captcha_text = resolved.read_text().strip()
                    resolved.unlink()
                    break

            if not captcha_text:
                print("  ❌ Timeout esperando CAPTCHA")
                continue

            print(f"  🔑 CAPTCHA: {captcha_text}")

            # ── Llenar formulario ──
            await page.evaluate(f"""
                (() => {{
                    document.getElementById('formInicioSesion:tipIdentificacion_input').value = '0';
                    document.getElementById('formInicioSesion:usuario').value = '{CEDULA}';
                    document.getElementById('formInicioSesion:clave').value = '{CLAVE}';
                    document.getElementById('formInicioSesion:captchaDigitado').value = '{captcha_text}';
                }})()
            """)
            await asyncio.sleep(0.5)

            # ── Submit ──
            await page.evaluate("""
                (() => {
                    document.getElementById('formInicioSesion:ejecutarPaso1').click();
                })()
            """)
            await asyncio.sleep(6)

            # ── Verificar resultado ──
            url = page.url
            content = await page.content()

            if "Agregar una cita" in content:
                print("✅✅✅ ¡LOGIN EXITOSO!")
                await page.screenshot(path=str(CAPTCHA_DIR / "login_success.png"), full_page=True)
                break  # Salir del loop de intentos

            # Buscar errores
            errors = await page.evaluate("""
                () => {
                    const selectors = ['.messagesError', '.error', '.ui-message', '.ui-messages', '[class*="error"]', '[class*="message"]'];
                    const messages = [];
                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const txt = el.textContent.trim();
                            if (txt && !messages.includes(txt)) messages.push(txt);
                        }
                    }
                    return messages;
                }
            """)
            for e in errors:
                print(f"  ❌ {e}")

            # Si el error es sobre sesión existente, intentar cerrar sesión
            if "Ya existe un usuario" in str(errors):
                print("  ⚠️ Hay sesión activa, intentando cerrar...")
                try:
                    await page.evaluate("""
                        (() => {
                            const btn = document.getElementById('formInicioSesion:btnCerrarSesion')
                                || document.querySelector('a[href*="logout"]')
                                || document.querySelector('a[href*="cerrar"]');
                            if (btn) btn.click();
                        })()
                    """)
                    await asyncio.sleep(2)
                except:
                    pass
                # Recargar la página de login
                await page.goto("https://edus.ccss.sa.cr/eduscitasweb/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

        else:
            print("\n❌ Se agotaron los intentos de login")
            await browser.close()
            return

        # ── Si llegamos aquí, el login fue exitoso ──
        print("\n[*] Login exitoso! Buscando cupos...")

        # Agregar cita
        print("[*] Abriendo formulario de nueva cita...")
        await page.evaluate("PrimeFaces.ab({s: 'formSIAC:btnMenuAdd', f: 'formSIAC'});")
        await asyncio.sleep(4)

        # Servicio
        await page.evaluate(f"""
            (() => {{
                const sel = document.getElementById('formSIAC:menuServicios_input');
                if (sel) {{
                    sel.value = '{SERVICIO}';
                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }})()
        """)
        await asyncio.sleep(3)

        # Especialidad
        await page.evaluate(f"""
            (() => {{
                const sel = document.getElementById('formSIAC:menuEspecialidades_input');
                if (sel) {{
                    sel.value = '{ESPECIALIDAD}';
                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }})()
        """)
        await asyncio.sleep(4)

        # Obtener cupos
        cupos = await page.evaluate("""
            () => {
                const table = document.getElementById('formSIAC:cuposDisponibles');
                if (!table) return [];
                const rows = table.querySelectorAll('tbody tr');
                const result = [];
                for (const row of rows) {
                    const cols = row.querySelectorAll('td');
                    if (cols.length >= 5) {
                        result.push({
                            fecha: cols[0].textContent.trim(),
                            hora: cols[1].textContent.trim(),
                            numero: cols[2].textContent.trim(),
                            consultorio: cols[3].textContent.trim(),
                            funcionario: cols[4].textContent.trim(),
                        });
                    }
                }
                return result;
            }
        """)

        filtrados = [c for c in cupos if c["fecha"] not in EXCLUIR_FECHAS]

        # Si hay fecha objetivo, quedarse solo con los cupos de esa fecha
        if FECHA_OBJETIVO:
            filtrados = [c for c in filtrados if c["fecha"] == FECHA_OBJETIVO]
            if not filtrados:
                print(f"📭 No hay cupos disponibles para la fecha {FECHA_OBJETIVO}")

        if not filtrados:
            print("📭 No hay cupos disponibles ahora")
        else:
            print(f"\n🎉 ¡{len(filtrados)} cupo(s) disponible(s)!")
            for c in filtrados:
                print(f"   📅 {c['fecha']} | 🕐 {c['hora']} | 🏥 {c['consultorio']} | 👨‍⚕️ {c['funcionario']}")

            # Intentar reservar el primero
            for cupo in filtrados:
                print(f"\n[*] Intentando reservar: {cupo['fecha']} {cupo['hora']}...")
                resultado = await page.evaluate("""
                    (cupo) => {
                        const table = document.getElementById('formSIAC:cuposDisponibles');
                        if (!table) return false;
                        const rows = table.querySelectorAll('tbody tr');
                        for (const row of rows) {
                            const cols = row.querySelectorAll('td');
                            if (cols.length >= 6 &&
                                cols[0].textContent.trim() === cupo.fecha &&
                                cols[1].textContent.trim() === cupo.hora) {
                                const btn = cols[5].querySelector('a, button');
                                if (btn) { btn.click(); return true; }
                            }
                        }
                        return false;
                    }
                """, cupo)

                if resultado:
                    await asyncio.sleep(3)
                    confirmado = await page.evaluate("""
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button, a'));
                            for (const btn of buttons) {
                                if (btn.textContent.trim() === 'Confirmar') {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if confirmado:
                        # Esperar respuesta del servidor antes de declarar éxito
                        await asyncio.sleep(4)
                        cuerpo = await page.inner_text("body")
                        cuerpo_lower = cuerpo.lower()

                        if any(m in cuerpo_lower for m in ["confirmada", "exitosa", "registrada", "agendada", "reservada", "comprobante"]):
                            print(f"\n✨ ¡¡Cita reservada!!")
                            print(f"   Fecha: {cupo['fecha']}")
                            print(f"   Hora: {cupo['hora']}")
                            print(f"   Consultorio: {cupo['consultorio']}")
                            print(f"   Funcionario: {cupo['funcionario']}")
                            # ✅ SALIR del loop: no intentar reservar más cupos
                            break
                        elif any(m in cuerpo_lower for m in ["asignada a otro", "no se encontraron", "no disponible", "no fue posible", "sin éxito", "error"]):
                            print(f"  ❌ El cupo {cupo['fecha']} {cupo['hora']} ya no está disponible")
                            print("  ⚠️ Probando siguiente cupo...")
                            continue
                        else:
                            print("  ⚠️ Estado incierto, capturando screenshot...")
                            await page.screenshot(path=str(CAPTCHA_DIR / "estado_incierto.png"))
                    else:
                        print("  ❌ No se pudo confirmar")
                else:
                    print("  ⚠️ Cupo no disponible, probando siguiente...")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())