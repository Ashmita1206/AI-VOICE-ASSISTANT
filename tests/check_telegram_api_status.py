import os, sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
from automation.telegram.telegram_automation import TelegramService
from pyrogram import Client

async def main():
    service = TelegramService()
    api_id_configured = bool(service._api_id)
    api_hash_configured = bool(service._api_hash)
    
    print("--- Telegram API Configuration Check ---")
    print(f"api_id configured = {'yes' if api_id_configured else 'no'}")
    print(f"api_hash configured = {'yes' if api_hash_configured else 'no'}")
    
    session_file_exists = os.path.exists("telegram_assistant.session") or os.path.exists("automation/telegram/telegram_assistant.session")
    print(f"session file exists = {'yes' if session_file_exists else 'no'}")
    
    session_authorized = False
    user_connected = False
    
    if api_id_configured and api_hash_configured and session_file_exists:
        client = Client(
            "telegram_assistant",
            api_id=service._api_id,
            api_hash=service._api_hash,
            no_updates=True,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=4.0)
            try:
                me = await asyncio.wait_for(client.get_me(), timeout=4.0)
                if me:
                    session_authorized = True
                    user_connected = True
                    print("session authorized = yes")
                    print("Telegram user/account connected = yes")
                    try:
                        contacts = await asyncio.wait_for(client.get_contacts(), timeout=4.0)
                        matches = [c for c in contacts if 'harshita' in (c.first_name or '').lower() or 'harshita' in (c.last_name or '').lower() or 'harshita' in (c.username or '').lower()]
                        print(f"Number of API matches for 'Harshita': {len(matches)}")
                    except Exception as ce:
                        print(f"Error fetching API contacts: {ce}")
                else:
                    print("session authorized = no")
                    print("Telegram user/account connected = no")
            except Exception as me_err:
                print(f"session authorized = no ({me_err})")
                print("Telegram user/account connected = no")
            await client.disconnect()
        except Exception as conn_err:
            print(f"session authorized = no (connect: {conn_err})")
            print("Telegram user/account connected = no")
    else:
        print("session authorized = no (session file not found or not logged in)")
        print("Telegram user/account connected = no")
        print("Number of API matches for 'Harshita': 0")

if __name__ == '__main__':
    asyncio.run(main())
