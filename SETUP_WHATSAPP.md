# Putting Kwacha Books on real WhatsApp

This takes about 2–3 hours the first time, spread over a day or two because Meta reviews a few things.
You'll end up with the bot answering on WhatsApp from a server that's always on.

Meta and Render update their screens often. If a button has moved, look for the same words nearby.

**What it costs:** Render Starter web service plus its smallest paid database came to about $13 a month as of
July 2026; check render.com/pricing. Meta charges per template message (the evening summary when a merchant
hasn't messaged in 24 hours); replies to merchants' own messages are generally cheap or free. Check Meta's
current WhatsApp pricing for Zambia. Everything else here is free.

---

## Part A. Accounts you need (30 minutes)

1. **GitHub** (github.com): free. Holds your code so Render can run it.
2. **Render** (render.com): sign up with your GitHub account. Add a payment card for the paid plans.
3. **Meta for Developers** (developers.facebook.com): log in with a Facebook account and register as a developer.
4. **A Meta Business portfolio** (business.facebook.com): create one for Kwacha Books if you don't have one.

## Part B. Put the code on GitHub (10 minutes)

1. On GitHub, click **New repository**. Name it `kwacha-books`, choose **Private**, and click **Create**.
2. Click **uploading an existing file**.
3. Open your unzipped `kwacha_books` folder, select **everything inside it** (not the folder itself), and drag it
   onto the GitHub page. Include `render.yaml`, `app.py`, the `kwacha_books`, `tests` and `web` folders.
4. Click **Commit changes**.

Never upload a file containing your tokens. The code reads them from Render's settings instead.

## Part C. Create the Meta app and get test details (20 minutes)

1. On developers.facebook.com, go to **My Apps → Create App**. Choose the option for connecting with customers
   through **WhatsApp**, and link your Business portfolio.
2. In the app, open **WhatsApp → API Setup**. Meta gives you a free **test phone number**. Note down:
   - the **Phone number ID** (a long number, not the phone number itself)
   - the **temporary access token** (lasts 24 hours; Part G replaces it with a permanent one)
3. Under **To**, add your own WhatsApp number as a recipient and enter the code Meta sends you.
   The test number can message up to 5 numbers you add this way.
4. Go to **App settings → Basic** and copy the **App secret** (click Show).
5. Make up a **verify token**: any long random string, e.g. `kwacha-7f3k9q2m8x`. Write it down.

## Part D. Deploy on Render (15 minutes)

1. In Render, click **New → Blueprint** and pick your `kwacha-books` repository.
2. Render reads `render.yaml` and shows a web service and a database. It asks for these values:

   | Setting | What to paste |
   |---|---|
   | WA_TOKEN | the temporary access token (Part C) |
   | WA_PHONE_ID | the Phone number ID (Part C) |
   | WA_APP_SECRET | the App secret (Part C) |
   | WA_VERIFY_TOKEN | the verify token you made up |
   | ALLOWED_NUMBERS | your own number, e.g. `260971234567` (no + or spaces) |
   | CONTACT_EMAIL | your email, shown on the privacy page |

3. Click **Apply**. The first deploy takes 3–5 minutes.
4. Open your service in Render and copy its address, like `https://kwacha-books-ab12.onrender.com`.
5. Visit that address followed by `/health`. You should see `{"ok":true}`.

To test for free first, change both `plan:` lines in `render.yaml` to `free` before step 1. The free server
sleeps after 15 minutes, so the first message after a quiet spell can take about a minute to answer, and the
free database is deleted after 30 days.

## Part E. Connect WhatsApp to your server (5 minutes)

1. In Meta, open **WhatsApp → Configuration**. Under **Webhook**, click **Edit**.
2. **Callback URL:** your Render address followed by `/webhook`, e.g. `https://kwacha-books-ab12.onrender.com/webhook`
3. **Verify token:** the one you made up. Click **Verify and save**.
4. Under **Webhook fields**, find **messages** and click **Subscribe**.

## Part F. Test it

On your phone, send **hi** to Meta's test number. Within a few seconds the bot should welcome you. Then:
reply **yes**, forward a real payment SMS, type **sale 120 sugar**, then **today**.

If nothing comes back, open your service in Render → **Logs** and see the troubleshooting table below.

## Part G. Replace the 24-hour token with a permanent one (15 minutes)

1. Go to business.facebook.com → **Settings → Users → System users** → **Add**. Name it `kwacha-bot`, role **Admin**.
2. Click **Assign assets**: give it your **app** (full control) and your **WhatsApp account** (full control).
3. Click **Generate token**, choose your app, set expiry to **Never**, and tick the permissions
   `whatsapp_business_messaging` and `whatsapp_business_management`.
4. Copy the token. In Render → your service → **Environment**, replace **WA_TOKEN** with it and save.
   Render restarts the bot automatically.

## Part H. Evening summaries (20 minutes, plus Meta's review)

**1. Create the message template.** WhatsApp only lets you message a merchant who hasn't written to you in
24 hours using a pre-approved template.

In **WhatsApp Manager → Message templates → Create template**:
- Category: **Utility**
- Name: `daily_summary`
- Language: **English** (if you pick "English (UK)" instead, add a setting `WA_SUMMARY_TEMPLATE_LANG` = `en_GB` in Render)
- Body:

  > Hello, here is your Kwacha Books summary for {{1}}. Total received: {{2}}. MTN: {{3}}, Airtel: {{4}}, Zamtel: {{5}}, Cash: {{6}}. Reply TODAY for the full details.

- Sample values: `Fri 30 Oct`, `K1,030.50`, `K250.00`, `K85.50`, `K500.00`, `K120.00`

Approval usually takes minutes to a day. If Meta rejects it for having too many variables, use this shorter body and
add a Render setting `WA_SUMMARY_PARAM_COUNT` = `2`:

  > Hello, here is your Kwacha Books summary for {{1}}. Total received: {{2}}. Reply TODAY for the full details.

**2. Schedule it.** Merchants who messaged in the last 24 hours get the full summary as normal text; others get
the template. Merchants with nothing recorded that day get nothing.

1. In Render → your service → **Environment**, copy the value of **TASK_TOKEN**.
2. Sign up free at **cron-job.org** and create a cron job:
   - URL: `https://YOUR-ADDRESS.onrender.com/tasks/evening-summaries?token=YOUR_TASK_TOKEN`
   - Schedule: every day at **19:00**, time zone **Africa/Lusaka**
   - Request method (under Advanced): **POST**
3. Use its **Test run** button. It should show something like `{"failed":0,"sent":1}`.

Running it twice in one evening is safe: each merchant gets one summary per day.

## Part I. From testing to a real pilot

Meta's test number only reaches the 5 numbers you add. For 20–30 merchants you need your own number:

1. Get a **new SIM** that has never been used on WhatsApp. That number becomes the bot.
2. In **WhatsApp → API Setup → Add phone number**, add it and choose a display name like "Kwacha Books".
   Meta reviews the display name.
3. Add a **payment method** in WhatsApp Manager so template messages can be charged.
4. Your app needs a **privacy policy URL**: use `https://YOUR-ADDRESS.onrender.com/privacy`. That page is
   already built; read it and have it checked before launch. Then switch the app to **Live**.
5. Meta may ask you to **verify your business** (registration documents) before raising your messaging limits.
6. In Render, update **WA_PHONE_ID** to the new number's ID, and put the pilot merchants' numbers in
   **ALLOWED_NUMBERS**, separated by commas. Remove it entirely when you open to everyone.

## Checking on the pilot

Visit `https://YOUR-ADDRESS.onrender.com/admin/stats?token=YOUR_TASK_TOKEN` to see how many merchants have
joined, how many payments are recorded, and how many need checking.

## Troubleshooting

| What you see | Likely cause and fix |
|---|---|
| Meta says the callback URL couldn't be verified | WA_VERIFY_TOKEN in Render doesn't exactly match what you typed in Meta, or the deploy hasn't finished. Check `/health` first. |
| You send "hi" and nothing comes back | In Meta, **messages** isn't subscribed (Part E step 4), or your number isn't added as a test recipient (Part C step 3). |
| Logs show `401` or "Error validating access token" | The temporary token expired. Do Part G. |
| Logs show "Rejected a webhook call with a bad signature" | WA_APP_SECRET is wrong. Copy it again from App settings → Basic. |
| Logs show `131030` or "Recipient phone number not in allowed list" | With the test number, add the recipient in API Setup first. |
| The bot replies "We're running a small pilot" | That number isn't in ALLOWED_NUMBERS. |
| Bot says it couldn't read an SMS | Paste that SMS (names and numbers removed) into `tests/samples.py` and adjust `parser.py`, or send it to whoever maintains the code. |
| Evening summary test shows `"failed": 1` | Check the logs. Usually the template isn't approved yet or its name/language doesn't match. |
