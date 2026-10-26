# Render classroom deployment

Live URL: **https://hackflow-class-demo.onrender.com/**

Verified on Render on 26 October 2026: sign-in, static assets, fresh PostgreSQL
migrations/seeds, Horizon's semantic ranking (Lina and Yasmine ahead), and
Passerelle's Figma mention / UI/UX inference. The skill-needs preview was left
unconfirmed for the presentation. Render's free dashboard does not expose
application RAM metrics; no exact hosted memory measurement is claimed.

Online Sami demo links (new database IDs differ from the local database):

- [Horizon teammate recommendations](https://hackflow-class-demo.onrender.com/participation/ai-challenge-2026/teams/2/candidates/)
- [Passerelle skill-needs assistant](https://hackflow-class-demo.onrender.com/participation/campus-solidaire-2026/teams/3/needs/add/?mode=idea)

This is a temporary demo: one Free web service and one Free PostgreSQL instance,
both in Frankfurt. The free database expires after 30 days. No paid disk or service
is configured. The web app sleeps after inactivity and uploads are ephemeral.

`render.yaml` creates the resources and a generated Django secret/admin password.
Deploy the current feature branch containing the lightweight English M2 model.
`build.sh` installs locked dependencies, downloads the 23 MB ONNX model, and
collects static assets. `start.sh` migrates PostgreSQL, initializes fictional demo
data once, and runs one Gunicorn worker with two threads. Training never runs on
the server. AI descriptions use English; the interface remains bilingual.

The separate `config.settings_render` selects only a dedicated Render PostgreSQL
database named `hackflow_db` (including a provider-generated suffix). Local
`config.settings` retains its original local-only database guard. DEBUG stays off
in HTTP. Secure cookies and HTTPS are enabled. PostgreSQL uses TLS.

On first start `seed_render_demo` creates the normal M1/M2/M3/M4 demo data,
English Horizon candidate profiles and Sami's Campus solidaire/Passerelle scenario.
Only the initialization process temporarily enables seed commands. It creates
`render.admin` last, inside the same transaction, as the completion marker;
subsequent starts preserve saved work. It does not copy personal local accounts.

- Normal demo login: `sami` / `Demo-Hack#2026`.
- Organizer: `organisatrice` / `Demo-Hack#2026`.
- Admin: `render.admin`; retrieve its generated password from the service's
  `RENDER_DEMO_ADMIN_PASSWORD` environment variable. Never commit that value.
- Store the existing Google key only in Render's private `GOOGLE_API_KEY`
  environment variable to enable the other modules' Gemini features.

For tomorrow: open the app before the presentation to wake the free service, then
visit both M2 AI screens to load the model. Use the Skills only / Skills + project
switch in AI Challenge/Horizon, then Campus solidaire/Passerelle's Add needs screen.
Analysis alone saves nothing. Uploaded files disappear on a web-service restart;
database records remain until the database's free instance expires. Re-upload
demo attachments if needed. Stop/remove the resources after the presentation.

The Render build/start logs and `/healthz/` show whether deployment succeeded.
