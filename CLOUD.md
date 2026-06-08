# Alert giornaliero nel cloud (gratis, senza PC acceso)

Questa guida attiva l'invio automatico del riepilogo **"Cosa fare oggi"** su Telegram
ogni mattina, eseguito gratuitamente da **GitHub Actions**. Non serve tenere il PC acceso
né un server.

> ⚠️ Il database in cloud è "usa e getta": viene ricostruito a ogni esecuzione, quindi
> **non conosce le tue posizioni reali di Trade Republic**. L'alert cloud si concentra su
> **segnali di mercato e opportunità d'acquisto su dati reali**. Per consigli sul tuo
> portafoglio specifico, usa l'app sul PC.

## Passi (una volta sola, ~10 minuti)

### 1. Crea un repository PRIVATO su GitHub
- Vai su https://github.com/new
- Nome a piacere (es. `investedge`), visibilità **Private** (importante).
- Crea il repository.

### 2. Carica il codice
Dalla cartella del progetto, in un terminale:

```powershell
cd C:\Users\domenicoizzoj\Documents\InvestEdge\InvestEdge
git init
git add .
git commit -m "InvestEdge"
git branch -M main
git remote add origin https://github.com/TUO_UTENTE/investedge.git
git push -u origin main
```

> Il file `backend/.env` con le tue chiavi **non** viene caricato (è in `.gitignore`).
> Le chiavi le inserirai come "secrets" nel passo 3.

### 3. Inserisci i secrets nel repository
Nel repo su GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
Aggiungi questi (i valori sono quelli del tuo `backend/.env`):

| Nome secret | Valore |
|---|---|
| `TELEGRAM_BOT_TOKEN` | il token del tuo bot |
| `TELEGRAM_CHAT_ID` | il tuo chat id |
| `ALPHA_VANTAGE_API_KEY` | la tua API key (per i dati reali) |
| `COINGECKO_API_KEY` | opzionale |
| `FRED_API_KEY` | opzionale |
| `ENABLE_REAL_DATA` | `true` |
| `ENABLE_REAL_NEWS` | `true` |

> Senza `ALPHA_VANTAGE_API_KEY` l'alert parte ugualmente ma su dati simulati.

### 4. Prova subito
Nel repo: **Actions → Daily Alert → Run workflow**. Dopo 1-2 minuti dovresti ricevere
l'alert su Telegram. Da lì in poi parte da solo ogni mattina.

## Orario

GitHub usa l'ora UTC. Nel file `.github/workflows/daily-alert.yml` la riga:

```yaml
- cron: "30 6 * * *"
```

significa 06:30 UTC ≈ **08:30 in Italia** (ora legale) / 07:30 (ora solare). Per cambiare
orario modifica quei numeri (`minuti ore * * *`) e fai push.

## Limiti onesti
- I tier gratuiti delle API hanno limiti giornalieri: l'app si ferma da sola e usa i dati
  che ha. Per ~25 asset una volta al giorno il tier gratuito Alpha Vantage è sufficiente.
- GitHub Actions su repo privato ha minuti gratuiti mensili abbondanti per un run/giorno.
- L'alert cloud non include i consigli sul tuo portafoglio reale (vedi nota sopra).

## Disattivare
Elimina il file `.github/workflows/daily-alert.yml` (e fai push), oppure in
**Actions → Daily Alert → ··· → Disable workflow**.
