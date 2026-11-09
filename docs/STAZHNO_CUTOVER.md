# STAZHNO / stazhno.ru cutover

## Brand

- Product name: СТАЖНО
- Primary domain: https://stazhno.ru
- Transactional sender: noreply@stazhno.ru
- Positioning: «Работа, где опыт имеет значение»

## Application cutover

1. Merge the rebrand only after Python/browser/PostgreSQL CI is green.
2. Keep the existing technical Timeweb domain until stazhno.ru is healthy.
3. In Timeweb App Platform open `opytno-production` -> Settings -> Domains -> Edit.
4. Attach `stazhno.ru`. If the domain is managed outside the Cloud account, add it as an external domain and use the A record shown by Timeweb.
5. Wait for DNS propagation and automatic Let's Encrypt certificate issuance.
6. Set:
   - `OPYT50_PUBLIC_URL=https://stazhno.ru`
   - `OPYT50_SMTP_USER=noreply@stazhno.ru`
   - `OPYT50_MAIL_FROM=noreply@stazhno.ru`
   - `OPYT50_SMTP_HOST=smtp.timeweb.ru`
   - `OPYT50_SMTP_PORT=465`
   - `OPYT50_SMTP_STARTTLS=0`
   - `OPYT50_SMTP_SSL=1`
7. Store the mailbox password only in Timeweb as `OPYT50_SMTP_PASSWORD`.
8. Redeploy.
9. Verify homepage, registration/login, job search, candidate/employer dashboards, verification email and password reset.
   - Verified production mail transport for `noreply@stazhno.ru`: `smtp.timeweb.ru:465` with implicit TLS.
10. Keep the technical `.twc1.net` address available during acceptance.

## Mail DNS

If Timeweb mail is used, verify the domain has the required Timeweb MX records and the provider-generated SPF/DKIM records before relying on transactional delivery.

## Rollback

If the custom domain or mail fails, keep the application available on the technical Timeweb domain and temporarily remove/disable SMTP host configuration. No database rollback is required for the rebrand.
