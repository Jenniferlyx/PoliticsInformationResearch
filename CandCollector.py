import json
import logging
import re
import requests
import traceback
from typing import Dict, Iterable, List
from tqdm import tqdm
import collections

from bs4 import BeautifulSoup
import pandas as pd

logger = logging.getLogger("CandCollector")


class CandCollector(object):
    url = "https://ballotpedia.org"
    positions = [
        "U.S. Senate",
        "Governor",
        "State Senate",
        "House of Representatives",
        "Supreme Court",
        "Appeals",
        "Governor",
        "U.S. House",
    ]
    year_matcher = re.compile(r"20\d\d")

    def __init__(self, states: Iterable[str], df_cand: pd.DataFrame=pd.DataFrame()):
        if df_cand.empty:
            df_cand = pd.DataFrame(columns=["Name"])
        self.df_cand = df_cand
        self.states = states

    @classmethod
    def scrape_detailed_info(self, page):
        position = ""
        status = "unknown"
        year = -float("inf")
        pages = page.find("div", id="toc", class_="toc").find_all_previous("p")
        if page.find("span", id="Biography", class_="mw-headline") and \
            page.find("span", id="Biography", class_="mw-headline").find_all_previous("p"):   
            pages += page.find("span", id="Biography", class_="mw-headline").find_all_previous("p")
            # e.g. https://ballotpedia.org/Donald_Trump
        for p in pages:
            text = p.text
            for status_option in ["lost", "won", "disqualified", "ran", "run", "is running for"]:
                if status_option in text:
                    status = status_option
                    year = max([year] + [int(y) for y in self.year_matcher.findall(text)])
                    # The default position is Secretary of State
                    position = "Secretary of State"
                    for pos in self.positions:
                        if pos in text:
                            position = pos
                            break
                    break
        contacts = page.findAll(
            "div", {"class": "widget-row value-only white"})
        info = {"Position": position, "Status": status, "Year": year}
        twitter_dict = collections.defaultdict(str)
        for contact in contacts:
            if "republican" in contact.text.lower():
                info["Party"] = "Republican"
            elif "democratic" in contact.text.lower():
                info["Party"] = "Democratic"
            elif "green" in contact.text.lower():
                info["Party"] = "Green"
            elif "independent" in contact.text.lower():
                info["Party"] = "Independent"
            elif "constitution" in contact.text.lower():
                info["Party"] = "Constitution"
            elif "libertarian" in contact.text.lower():
                info["Party"] = "Libertarian"
            if "twitter" in contact.text.lower():
                twitter_dict[contact.find("a").text] = contact.find("a")["href"]
        info["Twitter"] = twitter_dict
        return info

    def scrap_twitter_account(self, href: str, state: str) -> Dict[str, str]:
        """Scrap the twitter account and other information of the candidate from its personal webpage from ballotpedia"""
        for link in [href, href + "_({})".format(state)]:
            # e.g. https://ballotpedia.org/Steve_Farley
            res = requests.get(link)
            page = BeautifulSoup(res.text, features="lxml")
            if page.find("div", id="toc", class_="toc") is not None:
                return self.scrape_detailed_info(page)
            else:
                continue
        return None

    def find_profile(self, cand_page, state, href_set) -> List[Dict[str, str]]:
        '''Find the profile of all candidates running for election in a given state'''
        cands_info = list()
        for row in cand_page.find_all("a", href=True):
            name = row.text.strip()
            # if name != "Massachusetts State Senate":
            #     continue
            if name in self.df_cand["Name"] or "https" in name or name == "":
                continue
            try:
                href = row["href"]
                label = "_".join(row.text.split(" ")).lower()
                if href not in href_set and href.lower().endswith(label) and href.lower().startswith(
                    "https://ballotpedia.org/"
                ):
                    href_set.add(href)
                    info = self.scrap_twitter_account(href, state)
                    if info:
                        info["Name"], info["Href"], info["State"] = name, href, state
                        cands_info.append(info)
            except Exception:
                logger.error(f"{state} {name}: {traceback.format_exc()}")
        return cands_info
    
    def filter(self, row) -> pd.DataFrame:
        for pos in self.positions:
            if pos in row['Name']:
                return False
        return True

    def __call__(self) -> pd.DataFrame:
        """Fetch all the candidate information in a given state"""
        cand_info = list()
        href_set = set()
        for state in tqdm(self.states):
            state_page = requests.get(
                "{}/{}_elections,_2022".format(self.url, state))
            state_page = BeautifulSoup(state_page.text, features="lxml")
            for pos in self.positions:
                try:
                    cand_page = state_page.find("a", text=pos)["href"]
                    cand_page = requests.get(f"{self.url}{cand_page}")
                    cand_page = BeautifulSoup(cand_page.text, features="lxml")
                    cand_info.extend(self.find_profile(cand_page, state, href_set))
                except Exception:
                    logger.debug(
                        f"{pos} doesn't exist for state {state}: {traceback.format_exc()}")
            print(pd.DataFrame(cand_info))
        cand_info = pd.DataFrame(cand_info)
        cand_info = cand_info[cand_info.apply(self.filter, axis=1)]
        # e.g. https://ballotpedia.org/Massachusetts_State_Senate
        return cand_info

if __name__ == "__main__":
    with open("Data/GeoInfo.json", "r") as f:
        states = list(json.loads(f.read())["States"].values())
    collector = CandCollector(states)
    df_cand = collector()
    col_name = f"Status {pd.Timestamp.now().strftime('%Y%m%d')}"
    df_cand = df_cand.dropna(subset=["Position"]).rename(columns={"Status": col_name})
    df_cand.set_index(["Name"]).to_csv("Data/Candidates/Candidates_tmp.csv")
