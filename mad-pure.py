import requests
from bs4 import BeautifulSoup
import sys
import mmap
import os
import re
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from apkutils import APKUtils
from androhelper import AndroHelper

DEBUG = False
URL = "https://apkpure.com"

out_dir = "temp"
file_list_apps = ""
aapt_path = "aapt2"
MAX_NB_THREADS = 8
nb_threads = 4

with open('perms.json') as json_file :
    perms = json.load(json_file)


def download_apk(url, filename):
    req = requests.get(url, allow_redirects=True)
    open(filename, 'wb').write(req.content)


def search_dl_app(app_name, output_file):

    search_url = "https://apkpure.com/search?q={}&t=app".format(app_name)
    req = requests.get(search_url)

    # Check status code
    if req.status_code != 200:
        print("Error Occurred while processing {}".format(
            app_name), file=sys.stderr)
        sys.exit(-1)

    soup = BeautifulSoup(req.text, 'html.parser')

    path = soup.find_all('dl')[0].a["href"]

    url_app = URL + path + "/download?from=details"

    if DEBUG:
        print("[DEBUG] URL APP: " + url_app)

    # Follow redirect to download APK page
    req = requests.get(url_app, allow_redirects=True)

    soup = BeautifulSoup(req.text, 'html.parser')
    try:
        download_link = soup.findAll(id="download_link")[0]["href"]
    except IndexError as e:
        return

    if DEBUG:
        print("[DEBUG] DOWNLOAD LINK: " + download_link)

    download_apk(download_link, out_dir + "/" + output_file)
    dump_info(aapt_path, out_dir + "/" + output_file)


def process(file_apps_name, out_directory, nb_threads):
    if not os.path.isdir(out_directory):
        try:
            os.makedirs(out_directory)
        except OSError as e:
            print(e)

    with open(file_apps_name, "r+") as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        lines = m.read().decode("utf-8").strip().split("\n")

    with ThreadPoolExecutor(max_workers=nb_threads) as executor:
        results = {executor.submit(search_dl_app, re.sub('\W+', ' ', app_name), re.sub('\W+', '_', app_name) +".apk"):
                        app_name for app_name in lines if not app_name.startswith("#")}
    for res in as_completed(results):
        print(res.result())


def dump_info(aapt_path, apk_path):
    info = {}

    apk_utils = APKUtils(aapt_path)
    output_permissions = apk_utils.aapt_dump_apk("permissions", apk_path)
    output_badging = apk_utils.aapt_dump_apk("badging", apk_path)
    try:
        info["package_name"] = APKUtils.get_app_package_name(output_permissions.strip())
    except Exception as e:
        print(e)

    info["permissions"] = APKUtils.get_permissions(output_permissions)
    info["supported_arch"] = APKUtils.get_supported_architectures(output_badging)

    with open("perms.json", "r+") as f:
        perms_infos = json.load(f)

    try:
        andro_helper = AndroHelper(apk_path, apk_path+".out")
        info["malware"] = andro_helper.analyze()
    except Exception as e:
        print(e)

    if len(info["malware"]["packed_file"]):
        print("WARNING: %s contains packed apk(s)" % apk_path)

    for malware, found in info["malware"]["detected_malware"].items():
        if found > 0:
            print("ALERT: %s is probably a %s" % (apk_path, malware))
    try:
        with open(apk_path+".out/report.json", 'w') as file:
            file.write(json.dumps(info, indent=4, sort_keys=True))
    except FileNotFoundError as e:
        print(apk_path + " failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MAD-Pure",
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('-f', '--file', dest="file_list_apps",
                        help='File with applications name',
                        required=True)

    parser.add_argument('-o', '--out-dir', dest="out_dir",
                        help='Directory where apks will be stored. Default: ' + out_dir,
                        default=out_dir)

    parser.add_argument('-a', '--aapt2-path', dest="aapt_path",
                        help='Path of aapt2 binary. Default: check the PATH env')

    parser.add_argument('-t', '--threads', dest="nb_threads",
                        help='Number of threads to use, value between 1 and 8. Default: 4')

    args = parser.parse_args()

    if args.file_list_apps:
        file_list_apps = args.file_list_apps

    if not os.path.isfile(file_list_apps):
        print("File %s does not exist." % file_list_apps)
        exit(-1)

    if args.out_dir:
        out_dir = args.out_dir

    if args.aapt_path:
        aapt_path = args.aapt_path

    if args.nb_threads:
        nb_threads = int(args.nb_threads)
        if nb_threads < 0 or nb_threads > MAX_NB_THREADS:
            print("Max threads to use is %s" % MAX_NB_THREADS)

    process(file_list_apps, out_dir, nb_threads)
