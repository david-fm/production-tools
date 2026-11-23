"""Catálogo y gestor de modelos. Todo contra un servidor HTTP local: sin red real."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from audio_enhancer_engine import models
from audio_enhancer_engine.models import DownloadFile, ModelEntry, ModelError


class Server:
    def __init__(self) -> None:
        self.routes: dict[str, bytes] = {}
        self.chunked: set[str] = set()
        self.redirects: dict[str, str] = {}
        self.hits: dict[str, int] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                outer.hits[path] = outer.hits.get(path, 0) + 1
                if path in outer.redirects:
                    self.send_response(302)
                    self.send_header("Location", outer.redirects[path])
                    self.end_headers()
                    return
                body = outer.routes.get(path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                if path not in outer.chunked:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.close()


def fake_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


DFN3_FILES = ("enc.onnx", "erb_dec.onnx", "df_dec.onnx", "config.ini")


def entry(server: Server, blob: bytes, *, sha: str | None = None, archive: bool = True, size: int | None = None) -> ModelEntry:
    server.routes["/m.bin"] = blob
    f = DownloadFile("m.bin", server.base + "/m.bin", sha or hashlib.sha256(blob).hexdigest(), size or len(blob))
    return replace(models.DFN3, files=(f,), archive=archive, extract=DFN3_FILES if archive else (),
                   size_bytes=size or len(blob))  # fmt: skip


@pytest.fixture
def catalog(monkeypatch):
    def put(e: ModelEntry) -> ModelEntry:
        monkeypatch.setitem(models.CATALOG, e.id, e)
        return e

    return put


def good_tar() -> bytes:
    return fake_tar({f: b"ok" for f in DFN3_FILES})


def install(tmp_path, **kw):
    return models.install("deepfilternet3", models_dir=tmp_path, allow_http_for_tests=True, **kw)


# ---------- catálogo ----------


def test_install_verifies_and_marks_installed(server, catalog, tmp_path):
    e = catalog(entry(server, good_tar()))
    folder = install(tmp_path)
    assert models.entry_status(e, tmp_path) == "installed"
    assert (folder / "enc.onnx").read_bytes() == b"ok"
    assert (folder / models.MARKER).read_text() == e.fingerprint


def test_sha_mismatch_is_rejected_and_nothing_is_installed(server, catalog, tmp_path):
    e = catalog(entry(server, b"contenido manipulado", sha="0" * 64))
    with pytest.raises(ModelError, match="sha256"):
        install(tmp_path)
    assert models.entry_status(e, tmp_path) == "missing"
    assert not list(tmp_path.glob(".deepfilternet3.*"))


def test_tar_with_malicious_paths_cannot_escape(server, catalog, tmp_path):
    members = {f"tmp/export/{f}": b"ok" for f in DFN3_FILES} | {"../../evil.txt": b"x"}
    catalog(entry(server, fake_tar(members)))
    folder = install(tmp_path / "m")
    assert sorted(p.name for p in folder.iterdir()) == sorted([*DFN3_FILES, ".ok"])
    assert not (tmp_path / "evil.txt").exists()


def test_incomplete_package_is_not_installed(server, catalog, tmp_path):
    e = catalog(entry(server, fake_tar({"enc.onnx": b"e"})))
    with pytest.raises(ModelError, match="no contiene"):
        install(tmp_path)
    assert models.entry_status(e, tmp_path) == "missing"
    assert not list(tmp_path.glob(".deepfilternet3.*"))


@pytest.mark.parametrize("chunked", [False, True])
def test_oversize_download_is_cut_with_or_without_content_length(server, catalog, tmp_path, chunked):
    blob = good_tar() + b"x" * 5_000_000
    catalog(entry(server, blob, size=1000))  # declarado 1000 B: el tope es ~1 MiB
    if chunked:
        server.chunked.add("/m.bin")
    with pytest.raises(ModelError, match="tamaño"):
        install(tmp_path)
    assert not list(tmp_path.glob(".deepfilternet3.*"))


def test_insufficient_disk_is_reported_before_downloading(server, catalog, tmp_path, monkeypatch):
    catalog(entry(server, good_tar()))
    monkeypatch.setattr(models.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10})())
    with pytest.raises(ModelError, match="Espacio insuficiente"):
        install(tmp_path)
    assert server.hits.get("/m.bin", 0) == 0


def test_cancel_cleans_partial_files(server, catalog, tmp_path):
    catalog(entry(server, good_tar() + b"x" * 3_000_000, size=4_000_000))
    with pytest.raises(ModelError, match="cancelado"):
        install(tmp_path, cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_concurrent_installs_of_same_id_download_once(server, catalog, tmp_path):
    e = catalog(entry(server, good_tar()))
    results, errors = [], []

    def run():
        try:
            results.append(install(tmp_path))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors and len(results) == 4
    assert server.hits["/m.bin"] == 1
    assert models.entry_status(e, tmp_path) == "installed"


def test_v010_install_is_recognised_without_downloading(server, catalog, tmp_path):
    """El marcador de v0.1.0 guarda el sha256 del paquete: debe reconocerse sin volver a descargar."""
    e = catalog(entry(server, good_tar()))
    folder = models.model_folder("deepfilternet3", tmp_path)
    folder.mkdir(parents=True)
    for f in DFN3_FILES:
        (folder / f).write_bytes(b"viejo")
    (folder / models.MARKER).write_text(e.fingerprint)
    assert models.entry_status(e, tmp_path) == "installed"
    install(tmp_path)
    assert server.hits.get("/m.bin", 0) == 0
    assert models.is_installed(folder)


def test_different_fingerprint_is_outdated_and_gets_reinstalled(server, catalog, tmp_path):
    e = catalog(entry(server, good_tar()))
    folder = models.model_folder("deepfilternet3", tmp_path)
    folder.mkdir(parents=True)
    for f in DFN3_FILES:
        (folder / f).write_bytes(b"viejo")
    (folder / models.MARKER).write_text("0" * 64)
    assert models.entry_status(e, tmp_path) == "outdated"
    assert (install(tmp_path) / "enc.onnx").read_bytes() == b"ok"


def test_truncated_install_without_marker_is_repaired(server, catalog, tmp_path):
    catalog(entry(server, good_tar()))
    folder = models.model_folder("deepfilternet3", tmp_path)
    folder.mkdir(parents=True)
    (folder / "enc.onnx").write_bytes(b"truncado")
    assert (install(tmp_path) / "enc.onnx").read_bytes() == b"ok"


def test_model_in_use_cannot_be_removed_or_reinstalled(server, catalog, tmp_path):
    e = catalog(entry(server, good_tar()))
    install(tmp_path)
    with models.use_models(["deepfilternet3"], tmp_path):
        with pytest.raises(ModelError, match="en uso"):
            models.remove("deepfilternet3", tmp_path)
        (models.model_folder("deepfilternet3", tmp_path) / models.MARKER).write_text("0" * 64)  # desactualizado
        with pytest.raises(ModelError, match="en uso"):
            install(tmp_path)
    (models.model_folder("deepfilternet3", tmp_path) / models.MARKER).write_text(e.fingerprint)
    assert models.remove("deepfilternet3", tmp_path) is True
    assert models.entry_status(e, tmp_path) == "missing"


def test_use_models_rejects_missing_model(tmp_path):
    with pytest.raises(ModelError, match="no está instalado"), models.use_models(["kim-vocal-2"], tmp_path):
        pass


def test_invalid_model_ids_are_rejected(tmp_path):
    for bad in ("../x", "a/b", "", ".oculto"):
        with pytest.raises(ModelError):
            models.model_folder(bad, tmp_path)


def test_catalog_lists_defaults_and_licences(tmp_path):
    items = {m["id"]: m for m in models.list_models(tmp_path)}
    assert items["deepfilternet3"]["default"] is True and items["deepfilternet3"]["status"] == "missing"
    assert items["kim-vocal-2"]["default"] is False and items["kim-vocal-2"]["verified_license"] is False


# ---------- Hugging Face ----------


def onnx_bytes(*, domain: str | None = None, external: bool = False) -> bytes:
    """ONNX mínimo (a mano) para probar las comprobaciones de seguridad."""

    def varint(n: int) -> bytes:
        out = b""
        while True:
            b = n & 0x7F
            n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n:
                return out

    def ld(field: int, payload: bytes) -> bytes:
        return varint(field << 3 | 2) + varint(len(payload)) + payload

    def vi(field: int, value: int) -> bytes:
        return varint(field << 3) + varint(value)

    tensor = ld(8, b"w") + (ld(13, ld(1, b"location") + ld(2, b"../../secreto.bin")) + vi(14, 1) if external else ld(9, b"\0\0\0\0"))
    node = ld(7, domain.encode()) if domain is not None else b""
    graph = ld(1, node) + ld(5, tensor)
    opset = ld(8, ld(1, b"") + vi(2, 17))
    return vi(1, 8) + ld(7, graph) + opset


def test_onnx_safety_checks(tmp_path):
    ok, ext, custom = (tmp_path / n for n in ("ok.onnx", "ext.onnx", "custom.onnx"))
    ok.write_bytes(onnx_bytes())
    ext.write_bytes(onnx_bytes(external=True))
    custom.write_bytes(onnx_bytes(domain="evil.ops"))
    models.check_onnx_safe(ok)
    with pytest.raises(ModelError, match="external_data"):
        models.check_onnx_safe(ext)
    with pytest.raises(ModelError, match="personalizados"):
        models.check_onnx_safe(custom)
    (tmp_path / "basura.onnx").write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(ModelError, match="ONNX válido"):
        models.check_onnx_safe(tmp_path / "basura.onnx")


REV = "a" * 40


def hf(server: Server, repo: str, files: dict[str, bytes], *, license_: str | None = "mit") -> str:
    api = {"sha": REV, "cardData": {"license": license_} if license_ else {},
           "siblings": [{"rfilename": n, "size": len(b)} for n, b in files.items()]}  # fmt: skip
    server.routes[f"/api/models/{repo}"] = json.dumps(api).encode()
    for n, b in files.items():
        server.routes[f"/api/models/files/{REV}/{n}"] = b
    return server.base + "/api/models/"


def install_hf(server, tmp_path, repo="alguien/modelo", **kw):
    return models.install_hf(repo, models_dir=tmp_path, allowed=lambda _u: True, **kw)


def test_hf_install_pins_revision_and_records_unverified(server, tmp_path):
    data = onnx_bytes()
    base = hf(server, "alguien/modelo", {"m.onnx": data})
    info = install_hf(server, tmp_path, api_base=base)
    assert info["revision"] == REV and info["verified_license"] is False and info["license"] == "mit"
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    listed = {m["id"]: m for m in models.list_models(tmp_path)}[info["id"]]
    assert listed["source"] == "huggingface" and listed["verified_license"] is False


@pytest.mark.parametrize("repo", ["../x/y", "a", "http://evil.com/x", "a/b/c", "a/..", "a b/c", "/a/b", ""])
def test_hf_rejects_invalid_repo_names(tmp_path, repo):
    with pytest.raises(ModelError, match="Repositorio inválido"):
        models.install_hf(repo, models_dir=tmp_path)


def test_hf_only_accepts_onnx(server, tmp_path):
    base = hf(server, "alguien/pesos", {"model.pt": b"pickle", "model.safetensors": b"st", "model.bin": b"b"})
    with pytest.raises(ModelError, match="ningún archivo .onnx"):
        install_hf(server, tmp_path, "alguien/pesos", api_base=base)


def test_hf_several_onnx_need_an_explicit_choice(server, tmp_path):
    base = hf(server, "alguien/varios", {"a.onnx": onnx_bytes(), "b.onnx": onnx_bytes()})
    with pytest.raises(ModelError, match="Hay varios"):
        install_hf(server, tmp_path, "alguien/varios", api_base=base)
    assert install_hf(server, tmp_path, "alguien/varios", file="b.onnx", api_base=base)["file"] == "b.onnx"


def test_hf_unsafe_onnx_is_not_installed(server, tmp_path):
    base = hf(server, "alguien/malo", {"m.onnx": onnx_bytes(external=True)})
    with pytest.raises(ModelError, match="external_data"):
        install_hf(server, tmp_path, "alguien/malo", api_base=base)
    assert [m for m in models.list_models(tmp_path) if m["source"] == "huggingface"] == []
    assert not list(tmp_path.glob(".hf--*"))


def test_hf_redirect_to_a_disallowed_host_is_blocked(server, tmp_path):
    base = hf(server, "alguien/redir", {"m.onnx": onnx_bytes()})
    server.redirects[f"/api/models/files/{REV}/m.onnx"] = "https://evil.example.com/m.onnx"
    with pytest.raises(ModelError, match="no permitido"):
        models.install_hf("alguien/redir", models_dir=tmp_path, api_base=base,
                          allowed=lambda u: u.startswith(server.base))  # fmt: skip


def test_hf_download_changing_size_midway_is_cut(server, tmp_path):
    data = onnx_bytes()
    base = hf(server, "alguien/crece", {"m.onnx": data})
    server.routes[f"/api/models/files/{REV}/m.onnx"] = data + b"x" * 3_000_000  # crece tras anunciar el tamaño
    server.chunked.add(f"/api/models/files/{REV}/m.onnx")
    with pytest.raises(ModelError, match="tamaño"):
        install_hf(server, tmp_path, "alguien/crece", api_base=base)
    assert not list(tmp_path.glob(".hf--*"))


def test_hf_host_allowlist():
    assert models._hf_allowed("https://huggingface.co/a/b/resolve/x/y.onnx")
    assert models._hf_allowed("https://cdn-lfs.hf.co/x")
    assert not models._hf_allowed("http://huggingface.co/x")  # solo HTTPS
    assert not models._hf_allowed("https://huggingface.co.evil.com/x")
    assert not models._hf_allowed("https://evil.com/huggingface.co")
