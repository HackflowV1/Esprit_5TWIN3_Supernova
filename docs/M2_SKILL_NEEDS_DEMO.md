# Sami — test the skill-needs assistant

The normal PostgreSQL database contains a second published hackathon,
**Campus solidaire 2026**, with Sami as captain of **Passerelle**.
Horizon and its teammate-recommendation scenario stay separate.

## Prepare

```powershell
uv run --locked python manage.py seed_demo
uv run --locked python manage.py seed_m2_skill_needs_demo
```

The command is for local demo use (`DEBUG=True`). It preserves existing passwords,
ideas, saved needs and registration cancellations on repeat runs. No schema
changes or new migrations are needed. The idea is English for the English encoder.

## Try it

1. Sign in as **sami**, using the existing demo password **Demo-Hack#2026**.
2. Open **Campus solidaire 2026 → My team → Add** in the skills-needed section.
3. Choose **Start from our idea**. The team's description is already filled in:

   > We need to simplify the donation signup steps, test screen usability with volunteers,
   > and make every action accessible using only the keyboard. We will sketch the screens in Figma.

4. Click **Suggest skills**. With the current model, **Figma** is identified as an
   explicit mention, while **UI/UX** is inferred from the work described, even though
   the text never names UI/UX. These are actual predictions, not hardcoded demo results.
5. Check the useful suggestions, choose levels and priorities, then confirm. They
   appear in the team's ordinary skills-needed list. Analysis alone saves nothing.
6. To repeat the full confirmation demo, remove those needs using the ordinary
   delete controls. The seed deliberately never deletes your saved work.

The AI idea and the earlier Horizon showcase profiles are English. The interface
still follows the user's French/English preference. Existing catalogue skill names
(such as `UI/UX`) are preserved so all modules use the same records.
