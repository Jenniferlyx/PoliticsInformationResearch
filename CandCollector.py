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
        "State House",
        "House of Representatives",
        "Supreme Court",
        "Appeals",
        "Governor",
        "U.S. House"
    ]
    parties = [
        "Republican",
        "Democratic",
        "Independent",
        "Green",
        "Constitution",
        "Libertarian",
        "Nonpartisan"
    ]
    year_matcher = re.compile(r"20\d\d")

    def __init__(self, states: Iterable[str], df_cand: pd.DataFrame=pd.DataFrame()):
        if df_cand.empty:
            df_cand = pd.DataFrame(columns=["Name"])
        self.df_cand = df_cand
        self.states = states

    @classmethod
    def scrape_profile_info(self, href: str) -> Dict[str, str]:
        """Scrap the twitter account and other information of the candidate from its personal webpage from ballotpedia"""
        res = requests.get(href)
        page = BeautifulSoup(res.text, features="lxml")
        if not page.find("div", class_="infobox person"):
            return None

        twitter_dict = collections.defaultdict(str)
        party = "unknown"
        status = "unknown"
        year = float("-inf")

        for p in page.find("div", class_="infobox person"):
            if p.find("a") and p.find("a") != -1:
                if "twitter" in p.find("a").text.lower():
                    twitter_dict[p.find("a").text] = p.find("a", href=True)["href"]
            if year == float("-inf") or status == "unknown":
                for s in ["Last election", "Last elected", "Date Elected", "Next election", "Last convention"]:
                    if s in p.text:
                        status = s
                        year = max([year] + [int(y) for y in self.year_matcher.findall(p.text)])
                        break
            if party == "unknown":
                for par in self.parties:
                    if par in p.text:
                        party = par
    
        info = {"Party": party, "Status": status, "Year": year, "Twitter": twitter_dict}
        return info

    def find_profile(self, cand_page, state, pos, href_set) -> List[Dict[str, str]]:
        '''Find the profile of all candidates running for election in a given state'''
        cands_info = list()
        for row in cand_page.findAll("div", class_="results_table_container"):
            for page in row.findAll("a"):
                href = page['href']
                if "#" in href or href in href_set:
                    continue
                try:
                    href_set.add(href)
                    info = self.scrape_profile_info(href)
                    if info:
                        info["Name"], info['Href'], info['Position'], info['State'] = page.text, href, pos, state
                        cands_info.append(info)
                except Exception:
                    logger.error(f"{state} {page.text}: {traceback.format_exc()}")
        return cands_info

    def __call__(self) -> pd.DataFrame:
        """Fetch all the candidate information in a given state"""
        cand_info = list()
        position_href_dict = collections.defaultdict(str)
        href_set = set()
        for state in tqdm(self.states):
            state_page = requests.get(
                "{}/{}_elections,_2022".format(self.url, state))
            state_page = BeautifulSoup(state_page.text, features="lxml")
            for row in state_page.findAll("div", class_="election-card", id="offices"):
                for page in row.findAll("a"):
                    for pos in self.positions:
                        if pos in page.text and page['href'] not in list(position_href_dict.values()):
                            position_href_dict[page.text] = page['href']
            for pos, page_link in position_href_dict.items():
                try:
                    cand_page = requests.get(f"{self.url}{page_link}")
                    cand_page = BeautifulSoup(cand_page.text, features="lxml")
                    cand_info.extend(self.find_profile(cand_page, state, pos, href_set))
                except Exception:
                    logger.debug(
                        f"{pos} doesn't exist for state {state}: {traceback.format_exc()}")
            print(pd.DataFrame(cand_info))
        return pd.DataFrame(cand_info)

if __name__ == "__main__":
    with open("Data/GeoInfo.json", "r") as f:
        states = list(json.loads(f.read())["States"].values())
    collector = CandCollector(states)
    df_cand = collector()
    col_name = f"Status {pd.Timestamp.now().strftime('%Y%m%d')}"
    df_cand = df_cand.dropna(subset=["Position"]).rename(columns={"Status": col_name})
    df_cand.set_index(["Name"]).to_csv("Data/Candidates/Candidates_tmp.csv")
