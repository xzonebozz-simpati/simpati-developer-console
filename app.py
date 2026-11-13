        return RedirectResponse(
            f"/clients?notice={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@app.post("/clients/{client_id}/status")
async def client_change_status(
    request: Request,
    client_id: str,
    csrf_token: str = Form(...),
    new_status: str = Form(..., alias="status"),
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan login ulang.",
            status_code=403,
        )

    if new_status not in ("active", "inactive"):
        return HTMLResponse(
            "Status klien tidak valid.",
            status_code=400,
        )

    try:
        client = await get_client(client_id)

        if not client:
            return RedirectResponse(
                "/clients?notice=Data+klien+tidak+ditemukan",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        await supabase_request(
            "PATCH",
            "clients",
            params={"id": f"eq.{client_id}"},
            data={
                "status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        message = (
            "Klien+berhasil+diaktifkan"
            if new_status == "active"
            else "Klien+berhasil+dinonaktifkan"
        )

        return RedirectResponse(
            f"/clients/{client_id}?notice={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    except SupabaseError as exc:
        from urllib.parse import quote
        return RedirectResponse(
            f"/clients/{client_id}?notice={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


# =========================================================
# MENU LAIN YANG MASIH DALAM PENGEMBANGAN
# =========================================================

def create_module_page(module):
    async def module_page(request: Request):
        if not authenticated(request):
            return RedirectResponse(
                "/login",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        return render_page(
            request,
            "modul.html",
            active_slug=module["slug"],
            module=module,
        )

    return module_page


for item in MENU_ITEMS:
    if item["slug"] in ("dashboard", "clients"):
        continue

    app.add_api_route(
        item["path"],
        create_module_page(item),
        methods=["GET"],
        response_class=HTMLResponse,
        name=item["slug"],
    )


# =========================================================
# LOGOUT
# =========================================================

@app.post("/logout")
async def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
