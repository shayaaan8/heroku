import datetime
import io
import json
import os
import random
import sys
import threading

import flask
import flask_cors
import googleapiclient
import requests

import src.config
import src.credentials
import src.metadata
import src.tree

print("================      STARTING      ================")
if os.getenv("LIBDRIVE_CONFIG"):
    config_str = os.getenv("LIBDRIVE_CONFIG")
    with open("config.json", "w+") as w:
        json.dump(json.loads(config_str), w)
    config = src.config.readConfig()
elif os.path.exists("config.json"):
    config = src.config.readConfig()
else:
    print("\033[91m\nThe \033[4mconfig.env\033[0m \033[91mfile or \033[91m\033[4mLIBDRIVE_CONFIG\033[0m \033[91menvironment variable is required for libDrive to function! Please create one at the following URL: https://libdrive-config.netlify.app/\n" + "\033[0m")
    sys.exit()

config, drive = src.credentials.refreshCredentials(config)

print("================  READING METADATA  ================")
if os.getenv("DRIVE_METADATA"):
    params = {"supportsAllDrives": True, "includeItemsFromAllDrives": True,
              "fields": "files(id,name)", "q": "'%s' in parents and trashed = false and mimeType = 'application/json'" % (os.getenv("DRIVE_METADATA")), "orderBy": "createdTime"}
    files = drive.files().list(**params).execute()["files"]
    if len(files) == 0:
        metadata = src.metadata.readMetadata(config)
    else:
        file = files[-1]
        request = drive.files().get_media(fileId=file["id"])

        fh = io.BytesIO()
        downloader = googleapiclient.http.MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        metadata = json.loads(fh.getvalue())

        try:
            os.mkdir("metadata")
        except:
            pass
        with open("metadata/%s" % (file["name"]), "w+") as w:
            json.dump(metadata, w)
else:
    metadata = src.metadata.readMetadata(config)


def create_app():
    app = flask.Flask(__name__, static_folder="build")
    config_categories = [d["id"] for d in config["category_list"]]
    metadata_categories = [d["id"] for d in metadata]
    if len(metadata) > 0 and sorted(config_categories) == sorted(metadata_categories):
        if datetime.datetime.utcnow() <= datetime.datetime.strptime(metadata[-1]["buildTime"], "%Y-%m-%d %H:%M:%S.%f") + datetime.timedelta(minutes=config["build_interval"]):
            return app
    print("================  WRITING METADATA  ================")
    buildThread = threading.Thread(target=src.metadata.writeMetadata, args=(
        config, drive), daemon=True).start()
    return app


app = create_app()
flask_cors.CORS(app)
app.secret_key = config["secret_key"]


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if (path != "") and os.path.exists("%s/%s" % (app.static_folder, path)):
        return flask.send_from_directory(app.static_folder, path)
    else:
        return flask.send_from_directory(app.static_folder, "index.html")


@app.route("/api/v1/auth")
def authAPI():
    config = src.config.readConfig()
    u = flask.request.args.get("u")  # USERNAME
    p = flask.request.args.get("p")  # PASSWORD
    a = flask.request.args.get("a")  # AUTH
    if any(u == account["username"] for account in config["account_list"]) and any(p == account["password"] for account in config["account_list"]):
        account = next(
            (i for i in config["account_list"] if i["username"] == u), None)
        return flask.jsonify(account)
    elif any(a == account["auth"] for account in config["account_list"]):
        account = next(
            (i for i in config["account_list"] if i["auth"] == a), None)
        return flask.jsonify(account)
    else:
        return flask.jsonify({"error": {"code": 401, "message": "The username and/or password provided was incorrect."}}), 401


@app.route("/api/v1/environment")
def environmentAPI():
    config = src.config.readConfig()
    a = flask.request.args.get("a")  # AUTH
    if any(a == account["auth"] for account in config["account_list"]):
        account = next(
            (i for i in config["account_list"] if i["auth"] == a), None)
        tmp_environment = {"account_list": account,
                           "category_list": config["category_list"]}
        return flask.jsonify(tmp_environment)


@app.route("/api/v1/metadata")
def metadataAPI():
    config = src.config.readConfig()
    tmp_metadata = src.metadata.readMetadata(config)
    a = flask.request.args.get("a")  # AUTH
    c = flask.request.args.get("c")  # CATEGORY
    q = flask.request.args.get("q")  # SEARCH-QUERY
    s = flask.request.args.get("s")  # SORT-ORDER
    r = flask.request.args.get("r")  # RANGE
    id = flask.request.args.get("id")  # ID
    if any(a == account["auth"] for account in config["account_list"]):
        if c:
            tmp_metadata = [
                next((i for i in tmp_metadata if i["categoryInfo"]["name"] == c), None)]
            if tmp_metadata:
                pass
            else:
                return flask.jsonify({"error": {"code": 400, "message": "The category provided could not be found."}}), 400
        if q:
            index = 0
            for category in tmp_metadata:
                tmp_metadata[index]["children"] = [
                    item for item in category["children"] if q.lower() in item["title"].lower()]
                index += 1
        if s:
            index = 0
            for category in tmp_metadata:
                if s == "alphabet-asc":
                    try:
                        tmp_metadata[index]["children"] = sorted(
                            category["children"], key=lambda k: k["title"])
                    except:
                        pass
                elif s == "alphabet-des":
                    try:
                        tmp_metadata[index]["children"] = sorted(
                            category["children"], key=lambda k: k["title"], reverse=True)
                    except:
                        pass
                elif s == "date-asc":
                    try:
                        tmp_metadata[index]["children"] = sorted(
                            category["children"], key=lambda k: tuple(map(int, k["releaseDate"].split('-'))))
                    except:
                        pass
                elif s == "date-des":
                    try:
                        tmp_metadata[index]["children"] = sorted(category["children"], key=lambda k: tuple(
                            map(int, k["releaseDate"].split("-"))), reverse=True)
                    except:
                        pass
                elif s == "popularity-asc":
                    try:
                        tmp_metadata[index]["children"] = sorted(
                            category["children"], key=lambda k: float(k["popularity"]))
                    except:
                        pass
                elif s == "popularity-des":
                    try:
                        tmp_metadata[index]["children"] = sorted(
                            category["children"], key=lambda k: float(k["popularity"]), reverse=True)
                    except:
                        pass
                elif s == "random":
                    try:
                        random.shuffle(tmp_metadata[index]["children"])
                    except:
                        pass
                else:
                    return None
                index += 1
        if r:
            index = 0
            for category in tmp_metadata:
                tmp_metadata[index]["children"] = eval(
                    "category['children']" + "[" + r + "]")
                index += 1
        if id:
            ids = src.metadata.jsonExtract(
                obj=tmp_metadata, key="id", getObj=True)
            for item in ids:
                if item["id"] == id:
                    tmp_metadata = item
                    tmp_metadata["children"] = []
                    if tmp_metadata.get("title") and tmp_metadata["type"] == "directory":
                        for item in src.tree.iterDrive(tmp_metadata, drive):
                            if item["mimeType"] == "application/vnd.google-apps.folder":
                                item["type"] = "directory"
                                tmp_metadata["children"].append(item)
                            else:
                                item["type"] = "file"
                                tmp_metadata["children"].append(item)
                    return flask.jsonify(tmp_metadata)
            tmp_metadata = drive.files().get(fileId=id, supportsAllDrives=True).execute()
            if tmp_metadata["mimeType"] == "application/vnd.google-apps.folder":
                tmp_metadata["type"] = "directory"
                tmp_metadata["children"] = []
                for item in src.tree.iterDrive(tmp_metadata, drive):
                    if tmp_metadata["mimeType"] == "application/vnd.google-apps.folder":
                        tmp_metadata["type"] = "directory"
                        tmp_metadata["children"].append(item)
                    else:
                        tmp_metadata["type"] = "file"
                        tmp_metadata["children"].append(item)

        return flask.jsonify(tmp_metadata)
    else:
        return flask.jsonify({"error": {"code": 401, "message": "The auth code provided was incorrect."}}), 401


@app.route("/api/v1/redirectdownload/<name>")
def downloadRedirectAPI(name):
    tmp_metadata = src.metadata.readMetadata(config)
    id = flask.request.args.get("id")
    ids = src.metadata.jsonExtract(obj=tmp_metadata, key="id", getObj=True)
    name = ""
    for item in ids:
        if item["id"] == id:
            name = item["name"]
    keys = [i for i in flask.request.args.keys()]
    values = [i for i in flask.request.args.values()]

    args = "?"
    for i in range(len(keys)):
        args += "%s=%s&" % (keys[i], values[i])
    args = args[:-1]

    if "cloudflare" in config:
        if config["cloudflare"] != "":
            return flask.redirect(config["cloudflare"] + "/api/v1/download/%s%s" % (name, args))
        else:
            return flask.redirect("/api/v1/download/%s%s" % (name, args))
    else:
        return flask.redirect("/api/v1/download/%s%s" % (name, args))


@app.route("/api/v1/download/<name>")
def downloadAPI(name):
    def download_file(streamable):
        with streamable as stream:
            stream.raise_for_status()
            for chunk in stream.iter_content(chunk_size=4096):
                yield chunk

    config = src.config.readConfig()

    if datetime.datetime.strptime(config["token_expiry"], "%Y-%m-%d %H:%M:%S.%f") <= datetime.datetime.utcnow():
        config, drive = src.credentials.refreshCredentials(config)

    a = flask.request.args.get("a")
    id = flask.request.args.get("id")
    if any(a == account["auth"] for account in config["account_list"]) and id:
        headers = {key: value for (
            key, value) in flask.request.headers if key != "Host"}
        headers["Authorization"] = "Bearer %s" % (config["access_token"])
        resp = requests.request(
            method=flask.request.method,
            url="https://www.googleapis.com/drive/v3/files/%s?alt=media" % (
                id),
            headers=headers,
            data=flask.request.get_data(),
            cookies=flask.request.cookies,
            allow_redirects=False,
            stream=True)
        excluded_headers = ["content-encoding",
                            "content-length", "transfer-encoding", "connection"]
        headers = [(name, value) for (name, value) in resp.raw.headers.items(
        ) if name.lower() not in excluded_headers]
        return flask.Response(flask.stream_with_context(download_file(resp)), resp.status_code, headers)
    else:
        return flask.jsonify({"error": {"code": 401, "message": "The auth code or ID provided was incorrect."}}), 401


@app.route("/api/v1/config", methods=["GET", "POST"])
def configAPI():
    config = src.config.readConfig()
    if flask.request.method == "GET":
        secret = flask.request.args.get("secret")
        if secret == config["secret_key"]:
            return flask.jsonify(config)
        else:
            return flask.jsonify({"error": {"code": 401, "message": "The secret key provided was incorrect."}}), 401
    elif flask.request.method == "POST":
        secret = flask.request.args.get("secret")
        if secret == None:
            secret = ""
        if secret == config["secret_key"]:
            data = flask.request.json
            data["token_expiry"] = str(datetime.datetime.utcnow())
            src.config.updateConfig(data)
            return flask.jsonify({"success": {"code": 200, "message": "libDrive is updating your config"}}), 200
        else:
            return flask.jsonify({"error": {"code": 401, "message": "The secret key provided was incorrect."}}), 401


@app.route("/api/v1/rebuild")
def rebuildAPI():
    config = src.config.readConfig()
    force = flask.request.args.get("force")
    if force == "true":
        a = flask.request.args.get("a")
        if any(a == account["auth"] for account in config["account_list"]):
            rebuildThread = threading.Thread(target=src.metadata.writeMetadata, args=(
                config, drive), daemon=True).start()
            return flask.jsonify({"success": {"code": 200, "message": "libDrive is building your new metadata"}}), 200
        else:
            return flask.jsonify({"error": {"code": 401, "message": "The secret key provided was incorrect."}}), 401
    else:
        metadata = src.metadata.readMetadata(config)
        build_time = datetime.datetime.strptime(
            metadata[-1]["buildTime"], "%Y-%m-%d %H:%M:%S.%f")
        if datetime.datetime.utcnow() >= build_time + datetime.timedelta(minutes=config["build_interval"]):
            rebuildThread = threading.Thread(target=src.metadata.writeMetadata, args=(
                config, drive), daemon=True).start()
            return flask.jsonify({"success": {"code": 200, "message": "libDrive is building your new metadata"}}), 200
        else:
            return flask.jsonify({"error": {"code": 425, "message": "The build interval restriction ends at %s UTC. Last build date was at %s UTC." % (build_time + datetime.timedelta(minutes=config["build_interval"]), build_time)}}), 425


@app.route("/api/v1/restart")
def restartAPI():
    config = src.config.readConfig()
    secret = flask.request.args.get("secret")
    if secret == config["secret_key"]:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        return flask.jsonify({"error": {"code": 401, "message": "The secret key provided was incorrect."}}), 401


@app.route("/api/v1/ping")
def pingAPI():
    return flask.Response("Pong")


if __name__ == "__main__":
    print("================   SERVING SERVER   ================")
    app.run(host="0.0.0.0", port=31145, threaded=True)
