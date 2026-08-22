#https://chatgpt.com/c/81d039d4-ea90-4286-ab52-3ace712a20ca
# This is a sample Python script.
import pygetwindow as gw
# from pywinauto.application import Application
import pyttsx3
from pywinauto import Application
import subprocess
from pywinauto.keyboard import send_keys
import pyperclip

# GPT HELP:  https://chat.openai.com/c/aec09a74-238d-4f97-b49a-b6ca98e1d810

# Note  need to set up dummy chrome profile if you want browser to remember things

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

from threading import Thread
import datetime
import traceback
import sys
import itertools
import os, re
import sqlite3
import inspect
import time as t
# import openai
from myGPT import myGPT
from myGPT2 import myGPT as myGPT2
# from selenium import webdriver
# import webdriver_manager
# from webdriver_manager.chrome import ChromeDriverManager
import inspect
import pyautogui

log = None


class BadPost(Exception):
    """Custom exception class for a specific error condition."""

    def __init__(self, message="An error occurred in my application"):
        self.message = message
        super().__init__(self.message)


class StartFromTop(Exception):
    def __init__(self, message="An error occurred in my application"):
        self.message = message
        super().__init__(self.message)


class PyAutoWrap:

    def __init__(self, home_url, home_url_pattern, profile):
        self.FAST_TYPE = True
        self.chrome_profile = profile
        self.CONTAINS = "contains"
        self.MATCH = "match"
        self.WHOLE = "whole"
        self.TXT = "text"
        self.ID = "id"
        self.CLASS = "class"
        self.BUTTON = "//button"
        self.LABEL = "//label"
        self.INPUT = "//input"
        self.P = "p"
        self.SELECT = "//select"
        self.LIST = "ul"
        self.OPTION = "option"
        self.LIST_ELEMENT = "li"
        self.TXTAREA = '//textarea'
        self.LINK = 'a'
        self.ARIA_LABEL = 'aria-label'
        self.H1 = "h1"
        self.SVG = "svg"
        self.DELTA_WAIT = .2
        self.ALL = float('inf')
        self.home_url = home_url
        self.home_url_pattern = home_url_pattern

    def uploadFile(self, fullPath):
        #file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
        #file_input.send_keys(fullPath)
        pass

    def nextNonBlankLine(self, file_handler):
        # This function will yield non-blank lines from the file
        line = ''
        while not line or line.strip()[:2] == "//":
            line = file_handler.readline()
            if len(line) == 0:
                break
            line = line.strip()
        return line

    def readRestNonBlank(self, file_handler):
        rest = ""
        line = "something"
        while line:
            line = self.nextNonBlankLine(file_handler)
            rest += line + '\n'
        return rest

    def nextOccurance(self, file_handler, substr, delim="\t", after=""):
        active = False
        line = "something"
        while line:
            line = self.nextNonBlankLine(file_handler)
            if after in line:
                active = True
            if active and substr == line[:len(substr)]:
                return line.split(delim)[1]

    def start_up(self):
        self.process = subprocess.Popen([self.chrome_path, f'--user-data-dir={self.chrome_profile}'])
        self.app = Application().connect(process=self.process.pid)
        t.sleep(5)
        self.sanitizeWindow()
        self.goToURL(self.home_url)

    def focus(self):
        self.app.top_window().set_focus()

    def getLock(self, delay=2, lockOnly=False):
        self.focus()
        if not lockOnly:
            print(f"doing stuff in {delay} secs")
            t.sleep(delay)
            self.openDevConsoleGuaranteed()
            self.loadJS()

    def loadJS(self):
        pyperclip.copy(self.clickFuncs)
        # don't use execute for this one
        send_keys("^v{ENTER}")

    def clickAllJS(self, js_var_name_of_list ):
        self.execute(f"clickAll({js_var_name_of_list})")

    def findAndClickJS(self, aspect, searchType, chooser, indexInList=0, txtCond="", findFrom = "null", varName= "", elementTypeFilter="*"):
        if len(varName) > 0:
            varName = "var " + varName + " = "
        if aspect is None:
            aspect = "null"

        if indexInList == self.ALL:
            indexInList = f"'all'"

        sep = "\""
        if type(chooser) == list:
            sep = ""

        executionStr = f'{varName}findAndClick("{aspect}", "{searchType}", {sep}{chooser}{sep}, {indexInList}, "{txtCond}", {findFrom}, "{elementTypeFilter}")'
        self.execute(executionStr)

    def smartClickJS(self, element, newTab=False):
        executionStr = f'smartClick({element}, {str(newTab).lower()} )'
        self.execute(executionStr)

    def findClosestRelativesJS(self, refWhat, refType, refXpath, targetWhat, targetType, targetXpath,
                             refElementFilterType="*", limit=10,
                             srchLvlLmt=float('inf')):
        if srchLvlLmt == float('inf'):
            srchLvlLmt = "Infinity"
        self.execute(f'var relatives = findClosestRelatives("{refWhat}", "{refType}", "{refXpath}", "{targetWhat}", "{targetType}", "{targetXpath}", "{refElementFilterType}", {limit},  {srchLvlLmt})')

    def releaseLock(self):
        pass

    def getCurrentURL(self):
        # get lock
        self.getLock()
        send_keys('^l')
        send_keys('^c')
        url = pyperclip.paste()
        # release lock
        self.releaseLock()

        return url

    def getJsResult(self, asThis=str):
        self.execute("copy($_)")
        returnVal = pyperclip.paste()
        return asThis(returnVal)
    def execute(self, text, enter=True, fastType=True, careful=False):
        if fastType:
            text = text.replace("{CONTROL}", "^")
            pyperclip.copy(text)

            if not careful:
                send_keys("^v" + (r'{ENTER}' if enter else ""))
            else:
                print(f'pasting {text}')
                send_keys("^v")
                send_keys("^a")
                send_keys("^c")
                txtFromCpy = pyperclip.paste()
                print(f'comparing *{text}* and *{txtFromCpy}*')
                if txtFromCpy == text:
                    print("Equal so hitting enter!")
                    send_keys("{ENTER}")
                else:
                    return -1

            t.sleep(.5)
        else:
            formatted_text = text.replace(" ", "{SPACE}")
            for char in "!@#$%^&*()-=_+":
                formatted_text = formatted_text.replace(char, "{" + char + "}")
            formatted_text = formatted_text.replace("{SHIFT}", "+")
            formatted_text = formatted_text.replace("{CONTROL}", "^")
            t.sleep(1)
            send_keys(formatted_text + (r'{ENTER}' if enter else ""))

    def execAndRet(self, f, typ_=str, varName = None):
        f()
        if varName is not None:
            self.execute(varName)
        return self.getJsResult(typ_)

    def openDevConsoleGuaranteed(self):
        send_keys("^c")
        copied = pyperclip.paste()
        if "http" in copied: # the site addr is highlighted
            t.sleep(1)
            self.openDevTools()

        cycle = -1
        while not self.isDevConsoleOpen():
            cycle += 1
            if cycle % 2 == 0:
                print("calling open CONSOLE")
                self.openDevConsole()
            else:
                print("calling open TOOLS")
                self.openDevTools()
        return

        """if self.isDevConsoleOpen():
            return

        self.openDevConsole()

        if self.isDevConsoleOpen():
            return

        self.openDevTools()

        if self.isDevConsoleOpen():
            return

        self.openDevConsole()"""

    def isDevConsoleOpen(self):
        t.sleep(1)
        ret = self.execute("var myX = 777;", careful=True)
        if ret == -1:
            return False
        ret = self.execute("myX", careful=True)
        if ret == -1:
            return False
        res = self.getJsResult()
        return res == "777"

    def openDevTools(self):
        send_keys('{VK_F12}')

    def openDevConsole(self):
        send_keys('^`')
    def goToURL(self, url):
        #get lock
        self.getLock(lockOnly=True)
        send_keys('^l')
        self.execute(url)
        #release lock
        self.releaseLock()

    def sanitizeWindow(self, title="New Tab"):
        lastLen = -1
        while len(self.app.windows()) != lastLen or len(self.app.windows()) == 0 :
            lastLen = len(self.app.windows())
            t.sleep(.2)
        print(f"the len is: {lastLen}")
        windows = self.app.windows()
        for win in windows:
            if title not in win.window_text():
                win.close()
            else:
                break
        self.app.top_window().maximize()
    def goToTab(self, tab_num):
        # browser has already switched tabs but program still needs to switch
        all_tabs = self.driver.window_handles
        self.driver.switch_to.window(all_tabs[tab_num])

    def goToNewTab(self, indexOfNewTab=None):
        if indexOfNewTab is None:
            # Get the current window handle
            current_handle = self.driver.current_window_handle

            # Get the list of all window handles
            all_handles = self.driver.window_handles

            # Find the index of the current window handle
            current_index = all_handles.index(current_handle)
            self.goToTab(current_index + 1)
        else:
            self.goToTab(indexOfNewTab)

    def select_tab_by_url_pattern(self, pattern):
        """
        Selects the first tab with a URL matching the given pattern and closes all other tabs.

        Parameters:
        - driver: The Selenium WebDriver instance.
        - pattern: The regular expression pattern to match the tab URL.
        """
        # Get handles for all open tabs
        all_tabs = self.driver.window_handles

        # Find the first tab with a URL matching the pattern
        matching_tab = None
        for tab in all_tabs:
            self.driver.switch_to.window(tab)
            if re.search(pattern, self.driver.current_url):
                matching_tab = tab
                break

        # If no matching tab is found, return without doing anything
        if not matching_tab:
            self.reportAction("No tab found with a URL matching the pattern.")
            while True:
                t.sleep(1)
            return

        # Close all other tabs
        for tab in all_tabs:
            if tab != matching_tab:
                self.driver.switch_to.window(tab)
                self.driver.close()

        # Switch to the matching tab
        self.driver.switch_to.window(matching_tab)

    def click_all(self, list_of_elements, delayBeforeEach=0, delayBeforeFirst=0, timeLimitForEach=10):
        t.sleep(delayBeforeFirst)
        for element in list_of_elements:
            self.smartClickJS(element)



    def write(self, string):
        if log is not None and not log.closed:
            log.write(string)

    def graduatedWait(self, cond, maxWait=2):
        timeWaited = 0
        waitAmt = .1
        while timeWaited < maxWait:
            if cond():
                break
            t.sleep(waitAmt)
            timeWaited += waitAmt
            waitAmt *= 2



    def handleCaptcha(self):
        cap = self.findAndClick(self.TXT, self.MATCH, "Solve with 2Captcha", timeLimit=.1, nohang=True)
        if cap is None:
            return True

        # self.smartClick(element=cap)
        try:
            while cap.text != 'Captcha solved!':
                if "error" in cap.text.lower() or "api_http" in cap.text.lower() or "seconds" in cap.text.lower():
                    # self.driver.back()
                    # return StartFromTop()
                    ret = self.findAndClick(self.WHOLE, self.WHOLE, "//iframe[@title='reCAPTCHA']")
                    if ret is not None:
                        t.sleep(2)
                        return True
                    else:
                        self.driver.back()
                        return StartFromTop()
                t.sleep(.25)
        except:
            return True

        return True



    def findClosestRelativesSlow(self, refWhat, refType, refXpath, targetWhat, targetType, targetXpath, refElementFilterType="*", limit=10,
                             srchLvlLmt=float('inf')):
        self.findAndClickJS(refWhat, refType, refXpath, txtCond="^&*(", varName="reference_", elementTypeFilter=refElementFilterType)
        self.execute("reference_")
        reference = self.getJsResult()

        if reference == "null":
            return
        relatives = []
        prvWait = self.DELTA_WAIT  # elementXpath
        self.DELTA_WAIT = .01
        level = 0
        self.execute("var relatives = [] ;")
        while True:
            self.findAndClickJS(targetWhat, targetType, targetXpath, txtCond="^&*(", indexInList=self.ALL, varName="relatives", findFrom="reference_")
            #relatives = self.findAndClick(targetWhat, targetType, targetXpath, indInList=self.ALL, timeLimit=limit,
            #                              txtCond='@#%   Not Supposed To Match  ^&*()', findFrom=reference)
            self.execute("relatives.length")
            numRels = self.getJsResult(int)
            if numRels > 0:
                break

            # update the parent
            self.execute("reference_ = reference_.parentNode")

            # check if already at top level
            parent = self.getJsResult()
            if parent == "null":
                break

            level += 1
            if level > srchLvlLmt:
                break
        self.DELTA_WAIT = prvWait

    def findFillMoveOn(self, what, type, elementXpath, fillContent, indInList=0):
        self.findAndClickJS(what, type, elementXpath, indexInList=indInList, varName="toFindAndFill")
        self.fillMoveOn("toFindAndFill", fillContent)

    def findFillEnter(self, what, type, elementXpath, fillContent, indInList=0):
        self.findAndClickJS(what, type, elementXpath, indexInList=indInList, varName="toFindAndFill")
        #element = self.findAndClick(what, type, elementXpath, indInList)
        send_keys("^a")
        self.execute(fillContent)


    def fillMoveOn(self, element, fillContent, step=20):
        self.execute(f"{element}.click()")
        self.execute(f"{element}.focus()")
        send_keys('{VK_F12}') #close the console so element is on focus
        send_keys('^a')
        self.execute(fillContent, False)
        send_keys('{VK_F12}')  # open console back up
        self.openDevConsoleGuaranteed()  # ensure it was actually opened
        t.sleep(5)


    def fillDropDown(self, drpElementName, content, reFindCmd=None):
        # first check if the drop down element already has the value we want
        self.execute(f'Array.from({drpElementName}.querySelectorAll("option")).find( opt => {{ return opt.value == {drpElementName}.value;}}).label')
        curDropVal = self.getJsResult()

        while curDropVal.lower() != content.lower():
            self.execute(f"{drpElementName}.click()")
            self.execute(f"{drpElementName}.focus()")
            send_keys('{VK_F12}')  # close the console so element is on focus
            self.execute(content, False, False)
            send_keys('{VK_F12}')  # open console back up
            self.openDevConsoleGuaranteed()  # ensure it was actually opened
            t.sleep(1)
            #now retrieve the value and check again
            if reFindCmd is not None:
                reFindCmd()
            self.execute(f'Array.from({drpElementName}.querySelectorAll("option")).find( opt => {{ return opt.value == {drpElementName}.value;}}).label')
            curDropVal = self.getJsResult()

    def get_parent(self, element, level=1):
        for i in range(level):
            element = element.find_element('xpath', '..')
        return element

    def get_child(self, element, level=1, indInLevel=1):
        '''Indexes start at 1 for this function'''
        finalPath = "."
        for _ in range(level):
            finalPath += f"/*[{indInLevel}]"
        return element.find_elements('xpath', finalPath)[0]

    def get_child_complex(self, element, easyPath):
        # Split the string by '/' and filter out any empty strings
        indices = filter(None, easyPath.split('/'))

        # Convert each index to the corresponding XPath segment
        segments = [f"*[{index}]" for index in indices]

        # Join the segments and prepend with '.'
        finalPath = './' + '/'.join(segments)

        try:
            return element.find_elements('xpath', finalPath)[0]
        except:
            return None

    def num_children(self, element):
        try:
            return len(element.find_elements('xpath', './*'))
        except:
            None

    def indexAmongSiblings(self, element):
        index = len(element.find_elements('xpath', './preceding-sibling::*'))
        return index + 1

    def getNextSibling(self, element):
        indOfSibling = self.indexAmongSiblings(element) + 1
        parent = self.get_parent(element)
        return self.get_child(parent, indInLevel=indOfSibling)

    def generate_full_xpath(self, element):
        # Base case: if the element is the root html element
        try:
            if element.tag_name == "html":
                return "/html"
        except Exception as e:
            traceback.print_exc()
            h = 4

        # Calculate the index of the current element among its siblings
        siblings = element.find_elements('xpath', "./preceding-sibling::" + element.tag_name)
        index = len(siblings) + 1

        # Recursively generate the XPath for the parent element
        parent_xpath = self.generate_full_xpath(element.find_elements('xpath', "./..")[0])

        # Combine the parent XPath and the current element's tag and index to generate the full XPath
        return f"{parent_xpath}/{element.tag_name}[{index}]"

    def xpath_or(self, *args):
        xpath = ""
        for arg in args:
            xpath += arg
            if arg != args[-1]:
                xpath += " | "
        return xpath

    def reportAction(self, actionMsg, reportStack=True, useFile=True):
        if useFile:
            self.outputFile.write(f"\n{actionMsg}\n")
        else:
            print(f"\n{actionMsg}\n")

        if reportStack:
            stack = inspect.stack()
            listFuncCalls = [frame.function for frame in stack]
            listFuncCalls.pop(0)
            funcStack = ' | '.join(listFuncCalls)
            if useFile:
                self.outputFile.write(f"\tFunction Stack: {funcStack}\n")
            else:
                print(f"\tFunction Stack: {funcStack}\n")

    def getCurrentEnv(self):
        self.getLock()
        proof = self.openDevConsoleGuaranteed()
        self.execute("document.URL")
        url = self.getJsResult()
        while url == "copy($_)":
            self.execute("document.URL")
            url = self.getJsResult()

        self.execute("document.title")
        titleText = self.getJsResult()
        while titleText == "copy($_)":
            self.execute("document.title")
            titleText = self.getJsResult()

        currentEnv = f"{url}|{titleText}"

        self.releaseLock()

        return currentEnv

    def escape_regex_special_chars(self, s: str) -> str:
        # List of regex special characters that need to be escaped
        special_chars = ['\\', '.', '^', '$', '*', '+', '?', '{', '}', '[', ']', '|', '(', ')']

        # make the markers more complex
        s = s.replace("((", "({[(")[::-1].replace("))", ")}])")[::-1]

        # Find all substrings that are enclosed between (( and ))
        special_substrings = re.findall(r'\(\{\[\(.*?\)\]\}\)', s)

        # Replace the special substrings in the original string with placeholders
        for i, substring in enumerate(special_substrings):
            s = s.replace(substring, f'PLACE&&&HOLDER{i}')

        # Replace '({[(' and ')]})' in the special substrings
        special_substrings = [substring.replace('({[(', '').replace(')]})', '') for substring in special_substrings]

        # Escape the special characters in the modified string
        for char in special_chars:
            s = s.replace(char, f'\\{char}')

        # Replace the placeholders with the original special substrings
        for i, substring in enumerate(special_substrings):
            s = s.replace(f'PLACE&&&HOLDER{i}', substring)

        return s


class IndeedHelper(PyAutoWrap):
    area_specifier_text = {"United States": 'City, State',
                           "Canada": "City, Province / Territory"}

    def __init__(self, info, masterMilestoneList):
        self.MML = masterMilestoneList
        nowTime = datetime.datetime.now().strftime("%Y_%m_%d %H.%M.%S")
        self.MY_PATH = ''  # "Users\\name\\c
        self.home_url = ""
        self.home_url_pattern = ""
        self.chrome_profile = "user-data-dir="
        self.chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.applicationsLeft = -1
        self.profiles = []
        self.profile_generator = None
        self.cur_profile = {}
        self.user_id = -1
        self.dataPath = "data\\"
        self.configPath = "config\\"
        self.promptsPath = 'prompts\\'

        self.details = {}
        self.JobDescriptionText = ''
        self.companyName = ''
        self.jobTitle = ''
        self.lifeSummary = ''
        self.headline = ''
        self.coverLetter = ''
        self.resumeSummary = ''
        self.skills = []
        self.tries = []
        self.jobs = []
        self.edus = []
        self.prev_questions = []

        self.Bad = -1
        self.FreeResponse = 0
        self.MultChoice = 1
        self.DropDown = 2
        self.FreeResponseLong = 3
        self.SelectApplicable = 4
        self.DateFill = 5
        self.firstName = ''
        self.lastName = ""
        self.headline = ''
        self.phone_num = ''
        self.email = ''
        self.areaSpec = ''
        self.zip = ''
        self.country = 'United States'

        self.eduRecords = info["edus"]
        self.jobRecords = info["jobs"]
        self.load_startup_info(info["mainInfo"])
        self.outputFile = open(f"{self.MY_PATH}output {nowTime}.txt", "w")

        self.load_life_summary()
        super().__init__(self.cur_profile["home"], self.home_url_pattern, self.chrome_profile)

        # load the javascript file
        jsFile = open("js\\click_2.js", "r")
        self.clickFuncs = jsFile.read()

        # self.load_edu()
        self.start_up()
        self.jobOpeningGenerator = self.process_job_openings()



    def today(self):
        # Get today's date
        today_date = datetime.date.today()

        # Format the date as "MM/DD/YYYY"
        formatted_date = today_date.strftime("%b %d, %Y")
        return formatted_date

    def today_mmddyyy(self):
        # Get today's date
        today_date = datetime.date.today()

        # Format the date as "MM/DD/YYYY"
        formatted_date = today_date.strftime("%m/%d/%Y")
        return formatted_date

    ##############################   START TRANSITION FUNCTIONS   ##################################

    def waitOneSecond(self):
        t.sleep(1)

    def closeDialog(self):
        self.findAndClickJS("aria-label", "contains", "close")

    def newApp(self):
        # get next opening
        next(self.jobOpeningGenerator)

    def startApplication(self):
        # click on the Apply Now button if it is there
        self.findAndClickJS("text", "match", "Applied", txtCond="GHJLKH")
        res = self.getJsResult()
        #if res != "null":
        #    return self.backToStart()

        self.findAndClickJS("text", "match", "Apply now", elementTypeFilter="button")
        return #self.findAndClick(self.TXT, self.MATCH, 'Apply now', checkNewTab=True, timeLimit=3)

    def updateContactInfo(self):
        return self.handleAddInfoPage()

    def startResume(self):
        return self.chooseToBuildIndeedResume()

    def hitEditFromReviewPage(self):
        self.findClosestRelativesJS(self.TXT, self.MATCH, "Resume", self.TXT, self.MATCH, "Edit")
        self.smartClickJS("relatives[0]")
        return

    def addResume(self):
        self.findAndClickJS(self.TXT, self.MATCH, "Continue", elementTypeFilter="button")

    def backToDidContactInfo(self):
        pass

    def startContactInfo(self):
        #self.getLock()
        #self.loadJS()
        self.findAndClickJS("id", "contains", 'edit-contact-info')
        return

    def startSummary(self):
        # remove if already there
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Summary', self.ID, self.CONTAINS, 'delete', 'h2',
                                            srchLvlLmt=2)
        self.clickAllJS("relatives")

        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Summary', self.WHOLE, self.WHOLE, self.BUTTON)
        self.smartClickJS("relatives[0]")
        return

    def startWorkExp(self):
        return self.do_work_exp()

    def startEdu(self):
        return self.do_edu()

    def startSkills(self):
        return self.do_skiils()

    def finishResume(self):
        self.findAndClickJS("text", "match", "Continue applying", elementTypeFilter="button")
        return

    def startAtTopOfReviewPage(self):
        pass

    def doContactInfo(self):
        return self.edit_contact_info()

    def goBackToStartCI(self):
        pass

    def doSummary(self):
        return self.do_summary()

    def goBackToStartSum(self):
        pass

    def doWorkExp(self):
        return self.do_work_exp()

    def goBackToStartWork(self):
        pass

    def doEdu(self):
        return self.do_edu()
        # return self.fillEducationInfo()

    def goBackToStartEdu(self):
        pass

    def doSkills(self):
        return self.do_skiils()

    def goBackToStartSkills(self):
        pass

    def doQuestions(self):
        return self.analyzeAndAnsQuestions()

    def keepGoing(self):
        path_4_button_containing_span = "//button[span[contains(text(),'Continue')]]"
        # return self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7, checkNewPage=True)
        self.findAndClickJS("text", "match", ["Continue", "Review your application", "Continue applying",
                                                        "Continue to application"], elementTypeFilter="button")
        return

    def continueFromPage(self):
        self.findAndClickJS("text", "match",  ["Continue", "Review your application", "Submit your application"],
                            elementTypeFilter="button")
        return

    def clickAddDocs(self):
        #  Find Supporting documents section and click on the add button
        try:
            addButton = self.findClosestRelativesJS(self.TXT, self.CONTAINS, 'Supporting documents',
                                                  self.WHOLE, self.WHOLE, "//a")
        except:
            self.reportAction("Skipping the 'Add Docs' part because there doesn't seem to be a section for adding CL")
            return None
        self.smartClickJS("relatives[0]")
        return

    def prepDBCommit(self):
        companyInfo = f"{self.companyName}~+~{self.jobTitle}~+~{self.JobDescriptionText}"

        # full name
        fullName = f"{self.firstName} {self.lastName}"

        # prev job info
        resume = f"{fullName}~+~{self.headline}~+~{self.jobs}~+~{self.edus}~+~{self.skills}~+~{self.resumeSummary}"

        # save the application in database
        # self.saveAppInDB(companyInfo, resume, self.coverLetter)
        self.saveAppInDB(self.companyName, self.jobTitle, self.JobDescriptionText, fullName,
                         self.headline, str(self.jobs), str(self.edus), str(self.skills),
                         self.resumeSummary, str(self.prev_questions), self.coverLetter)

        self.MML.append(datetime.datetime.now())

    def saveUserInDB(self):
        emailCol = "IndeedEmail"
        passCol = "IndeedPass"
        checker_query = """SELECT * FROM users WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                          email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
        insert_query = f"""INSERT INTO users (FirstName, LastName, PhoneNumber, 
                                 email, address, cityState, country, zip, {emailCol}, {passCol})
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        values = [self.firstName, self.lastName, self.phone_num, self.email,
                  self.addr, self.areaSpec, self.country, self.zip]
        conn = sqlite3.connect('IndHelperDB.db')
        cursor = conn.cursor()

        # Create the table if it doesn't exist
        # cursor.execute('''CREATE TABLE IF NOT EXISTS users
        #                         (id INTEGER PRIMARY KEY, FirstName TEXT, LastName TEXT, PhoneNumber TEXT,
        #                         email TEXT, address TEXT, cityState TEXT, country TEXT, zip TEXT)''')

        # Check if the record already exists
        cursor.execute(checker_query, values)

        # Fetch one record, if it exists
        existing_record = cursor.fetchone()

        # If the record does not exist, insert it
        if not existing_record:
            platformEmail = input(f"Enter {self.firstName}'s platform email")
            platformPass = input(f"Enter {self.firstName}'s platoform password")
            values.extend([platformEmail, platformPass])
            cursor.execute(insert_query, tuple(values))

            # Save (commit) the changes
            conn.commit()
            self.user_id = cursor.lastrowid
        else:
            self.user_id = existing_record[0]
            platformEmail = existing_record[-2]
            platformPass = existing_record[-1]
            for fname, field in [(emailCol, platformEmail), (passCol, platformPass)]:
                if not field:
                    values_ = tuple([input(f"What is {self.firstName}'s {fname}")] + values)
                    update_query = f"""UPDATE users SET {fname} = ? WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                                  email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
                    cursor.execute(update_query, values_)
            print(f"User '{self.firstName}' already exists.")

        # Close the connection
        conn.commit()
        conn.close()

    # def saveAppInDB(self, companyInfo, resumeInfo, coverLetter):
    def saveAppInDB(self, companyName, jobTitle, JobDescriptionText, fullName, headline, jobHist,
                    eduHist, skills, resumeSummary, prevQsAs, coverLetter):
        # https://chat.openai.com/c/17e56ec1-3cb5-4b4b-8b64-5632efe21023

        current_date = datetime.datetime.now().isoformat(' ', 'seconds')

        # Connect to the resume_records database
        conn = sqlite3.connect('IndHelperDB.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Create the records table with a foreign key for the user ID
        cursor.execute('''CREATE TABLE IF NOT EXISTS applications
                         (id INTEGER PRIMARY KEY, user_id INTEGER, DateTime TEXT, Platform TEXT,
                          companyName TEXT, jobTitle TEXT, JobDescriptionText TEXT, 
                          fullName TEXT, headline TEXT, jobHist TEXT, eduHist TEXT, 
                          skills TEXT, resumeSummary TEXT, QsAndAs TEXT, cover_letter TEXT,
                          FOREIGN KEY(user_id) REFERENCES users(id))''')

        # Insert a new application record with the user ID
        cursor.execute("""INSERT INTO applications (user_id, DateTime, Platform, companyName, jobTitle, JobDescriptionText, 
                          fullName, headline, jobHist, eduHist, skills, resumeSummary, QsAndAs, cover_letter)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (self.user_id, current_date, "Indeed", companyName, jobTitle, JobDescriptionText, fullName,
                        headline, jobHist, eduHist, skills, resumeSummary, prevQsAs, coverLetter))

        # update the fact that we've sent another application
        cursor.execute("""SELECT * FROM users WHERE id = ? """, (self.user_id,))
        userRec = cursor.fetchone()
        self.applicationsLeft = userRec["AppsLeft"]
        self.applicationsLeft -= 1
        cursor.execute("""UPDATE users SET AppsLeft = ? WHERE id = ? """, (self.applicationsLeft, self.user_id))

        # Save (commit) the changes
        conn.commit()

        # Close the connection
        conn.close()

    def closeAndReopenTab(self):
        #  use pygetwindow to find the proper window
        newTitle = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        self.driver.execute_script(f"document.title = '{newTitle}';")
        windows = gw.getWindowsWithTitle("Chrome")
        win_2_use = None
        for window in windows:
            if newTitle in window.title:
                win_2_use = window
                break

        # -------------------
        self.driver.close()
        win_2_use.activate()
        pyautogui.hotkey('ctrl', 'shift', 't')
        t.sleep(5)
        self.driver.switch_to.window(self.driver.window_handles[-1])

    def submitApp(self):

        # click the checkbox so they contact the person directly thru number too (maybe turn this off if you need to verify the leads)
        clickRes = self.findAndClick(self.WHOLE, self.WHOLE, "//input[@type='checkbox']", travelUp=1, timeLimit=1)
        if isinstance(clickRes, StartFromTop):
            return clickRes
        path_4_button_containing_span = "//button[span[contains(text(),'Submit')]]"
        sub = self.findAndClick(self.TXT, self.MATCH, "Submit your application", txtCond="asdfaf")
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sub)
        '''captchaWrap = self.findAndClick(self.ID, self.MATCH, "captcha-wrapper", txtCond="asdfads", timeLimit = 1)
        if captchaWrap is not None:
            pyautogui.moveTo(729, 582)
            t.sleep(1)
            pyautogui.click()
            t.sleep(3)'''
        # self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="cf-turnstile"]')
        self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="captcha-wrapper"]')

        clickRes = self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7,
                                     checkNewPage=True, newPageFollowsTimeLimit=True)
        if isinstance(clickRes, StartFromTop):
            return clickRes
        '''if True:
        t.sleep(5)
        print("do it now")
        pyautogui.hotkey('ctrl', 'shift', 't')'''
        if clickRes == -1:
            self.closeAndReopenTab()

        # self.prepDBCommit()

        return clickRes

    def addDocs(self):
        return self.do_cover_letter()

    def quickWaitAndRefresh(self):
        t.sleep(10)
        self.driver.refresh()
        t.sleep(60)

    def doDbThenbackToStart(self):
        self.prepDBCommit()
        self.backToStart()

    def backToStart(self):
        # go to first tab (ctrl + 1), get the title there (going to need to sanitize, so basically get page title, then compare that to the windows until you reach main window
        #  then go to last tab (ctrl + shift + tab) and ctrl + w every tab till you are at the first tab.
        send_keys("^1")
        self.openDevConsoleGuaranteed()
        self.execute("document.title")
        title = self.getJsResult()
        self.sanitizeWindow(title)
        send_keys('^+{TAB}')
        while title not in self.app.top_window().window_text():
            send_keys("^w")

    def backToInit(self):
        pass

    ##############################    END TRANSITION FUNCTIONS   ##################################

    def jaccard_similarity(self, str1, str2):
        set1 = set(str1)
        set2 = set(str2)
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        return len(intersection) / len(union)

    def process_job_openings(self):
        #  loop to go thru the different pages
        # open up click js file

        self.getLock()
        self.openDevConsoleGuaranteed()
        self.loadJS()
        while True:
            # find the list of job openings

            cssSelector = '".css-5lfssm.eu4oa1w0"'
            jsCode = f"const elements = document.querySelectorAll({cssSelector});"
            self.execute(jsCode)
            self.execute("elements.length")
            numOpenings = self.getJsResult(int)

            for open_i in range(numOpenings):
                self.MML.append(datetime.datetime.now())
                #  check if it's a non-interactable opening
                self.execute(f"var txt = elements[{open_i}].textContent")
                noText = 'txt.length == 0'
                notEasy = '! txt.includes("Easily apply" )'
                childNoCard = f'!elements[{open_i}].firstElementChild.className.includes("card")'
                self.execute(f'{noText} || {notEasy} || {childNoCard}')
                boolRes = self.getJsResult()
                if boolRes == "true":
                    continue

                self.findAndClickJS("element", "match", "a", txtCond="asdfff", findFrom=f"elements[{open_i}]", varName="ele")
                #self.execute(f'var ele = findAndClick("element", "match", "a", 0, "asdff", elements[{open_i}]);')
                self.execute('smartClick(ele, true);')

                #toggle the dev console of the new page
                self.openDevConsoleGuaranteed()
                self.loadJS()

                self.findAndClickJS("text", "match", "Apply now", txtCond="#$%^&*SDFGH")
                #self.execute('findAndClick("text", "match", "Apply now", 0, "#$%^&*SDFGH")')
                buttonSearch = self.getJsResult()

                if buttonSearch == 'null':
                    # means this is not a job that you can apply from Indeed site
                    self.backToStart()
                    continue

                # clear out prev Qs and As
                self.prev_questions.clear()

                # extract job info
                self.getPositionInfo()

                jobId = f"{self.companyName} {self.jobTitle}\n"
                f = open(self.MY_PATH + "skipped.txt", 'r')
                skippedCont = f.read()
                f.close()
                if jobId in skippedCont:
                    self.backToStart()
                    continue

                # check if this is one of the positions we want to avoid
                if self.jobContainsForbiddenCharacteristics():
                    self.reportAction(
                        f"Not proceeding with [{jobId}]... it contains characteristics this user wants to avoid", False)
                    f = open(self.MY_PATH + "skipped.txt", 'a')
                    f.write(jobId)
                    f.close()
                    self.backToStart()
                    continue

                # toggle the dev console again
                self.releaseLock()

                # load jobs and change job description based on the details of current job
                self.load_jobs(), self.MML.append(datetime.datetime.now())

                # load education history
                self.load_edu(), self.MML.append(datetime.datetime.now())

                # generate CL
                self.generateCL(), self.MML.append(datetime.datetime.now())

                # generate skills
                self.generateSkills(), self.MML.append(datetime.datetime.now())

                # generate headline
                self.generateHeadline(), self.MML.append(datetime.datetime.now())

                # resume summary
                self.generateSummary(), self.MML.append(datetime.datetime.now())

                # yield execution back to calling method
                yield

                # received executiong back.  Get the lock again and then open dev console
                self.getLock()
                self.openDevConsoleGuaranteed()

            #nextButton = self.findAndClick(self.ARIA_LABEL, self.MATCH, 'Next Page')
            self.findAndClickJS("aria-label", "match", "Next Page")
            nextButton = self.getJsResult()

            # if url1 and url2 are not different, we have hit the last page of the current profile
            if nextButton == "null":
                self.cur_profile = next(self.profile_generator)
                self.goToURL(self.home_url)

    def chooseToBuildIndeedResume(self):
        #self.getLock()
        #self.openDevConsoleGuaranteed()
        #self.loadJS()
        self.findAndClickJS("data-testid", "match", "IndeedResumeCard-input")
        self.findAndClickJS("text", "contains", "Edit resume", elementTypeFilter="button")

        #self.releaseLock()
        return

    def handleAddInfoPage(self):
        #self.getLock()  #PHONE NUMBER STILL FUCKING UP
        #self.loadJS()
        self.findAndClickJS("element", None, "h1", varName="title")
        self.execute("title && title.textContent == 'Add your contact information'")
        def condExec(f):
            self.execute("relatives.length")
            len = self.getJsResult(int)
            if len > 0:
                f()
        if self.getJsResult() == 'true':
        #if title is not None and title.text == 'Add your contact information':
            self.findClosestRelativesJS(self.TXT, self.MATCH, 'First name', self.WHOLE, self.WHOLE, '//input', "label")
            condExec( lambda: self.fillMoveOn("relatives[0]", self.firstName) )
            self.findClosestRelativesJS(self.TXT, self.MATCH, 'Last name', self.WHOLE, self.WHOLE, '//input', "label")
            condExec( lambda: self.fillMoveOn("relatives[0]", self.lastName))
            try:
                self.findClosestRelativesJS(self.TXT, "contains", 'Phone number', self.WHOLE, self.WHOLE, '//input', "label")
                condExec( lambda: self.fillMoveOn("relatives[0]", self.phone_num))
            except:
                print("No phone number field found")
                pass

            #self.findClosestRelativesJS(self.TXT, "contains", IndeedHelper.area_specifier_text[self.country],
            #                                   self.WHOLE, self.WHOLE, '//input', "label")
            #condExec( lambda: self.fillMoveOn("relatives[0]", self.areaSpec))

            # click on change country button
            #self.findAndClickJS("text", "match", "Change country", elementTypeFilter="button")


            self.findAndClickJS("text", "match", "Continue")
            return #self.findAndClick(self.TXT, self.MATCH, "Continue", checkNewPage=True)

    def edit_contact_info(self):
        #self.getLock()
        #self.loadJS()
        def condExec(f):
            self.execute("relatives.length")
            len = self.getJsResult(int)
            if len > 0:
                f()

        self.findClosestRelativesJS(self.TXT, "contains", 'First name', self.WHOLE, self.WHOLE, self.INPUT, "label")
        self.fillMoveOn("relatives[0]", self.firstName)

        self.findClosestRelativesJS(self.TXT, "contains", 'Last name', self.WHOLE, self.WHOLE, self.INPUT, "label")
        self.fillMoveOn("relatives[0]", self.lastName)

        self.findClosestRelativesJS(self.TXT, "contains", 'Headline', self.WHOLE, self.WHOLE, self.INPUT, "label")
        self.fillMoveOn("relatives[0]", self.headline)  # need GPT

        self.findClosestRelativesJS(self.TXT, "contains", 'Phone', self.WHOLE, self.WHOLE, self.INPUT, "legend")
        condExec( lambda: self.fillMoveOn("relatives[0]", self.phone_num) ) # need GPT

        self.findClosestRelativesJS(self.ID, self.CONTAINS, 'showPhoneNumber', self.WHOLE, self.WHOLE, self.INPUT)

        if self.execAndRet(lambda: self.execute( "relatives[0].checked" )) != 'true':
            self.smartClickJS("relatives[0]")

        # get the button that will make drop down show up
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON, "label")
        self.execute("relatives[0].click()")

        #get the dropdown now
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT, "label")
        self.fillDropDown("relatives[0]", self.country)


        self.findClosestRelativesJS(self.TXT, self.CONTAINS, IndeedHelper.area_specifier_text[self.country], self.WHOLE,
                                  self.WHOLE, self.INPUT, "label")
        self.fillMoveOn("relatives[0]", self.areaSpec)  # need GPT

        self.findClosestRelativesJS(self.TXT, self.CONTAINS, 'Postal code', self.WHOLE, self.WHOLE, '//input', "label")
        self.fillMoveOn("relatives[0]", self.zip)  # need GPT

        self.findAndClickJS("text", "match", "Save", elementTypeFilter="button")
        #result = self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, checkNewPage=True, timeLimit=.5)

        if self.getJsResult() == "null":
            self.findAndClickJS("aria-label", "match", "Back")
            #result = self.findAndClick(self.ARIA_LABEL, self.MATCH, 'Back', checkNewPage=True, timeLimit=5)
        print("waiting 3 secs for page content to load ")
        t.sleep(3)

        return

    def do_summary(self):
        txtBoxPath = "//div[@role='textbox']"
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, self.resumeSummary)  # need GPT
        self.findAndClickJS("text", "match", "Save", elementTypeFilter="button")
        print("waiting 3 secs for page content to load ")
        t.sleep(3)
        return #self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.5, checkNewPage=True)



    def handleEdu(self, edu: dict):
        eduLvl, fieldOS, schoolName, cityState, current, fromDate, toDate, country = tuple(edu.values())
        current = "y" in current.lower()

        # education level
        self.findFillMoveOn(self.ID, self.CONTAINS, 'educationLevel', eduLvl)

        # field of study
        self.findFillMoveOn(self.ID, self.CONTAINS, 'fieldOfStudy', fieldOS)

        # school name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'school', schoolName)

        # country location
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON, "label")
        self.smartClickJS("relatives[0]")

        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT, "label")
        self.fillDropDown("relatives[0]", self.country )

        # school location
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        frmMonCont, frmYrCont = tuple(fromDate.split(" "))


        # current position
        if current:
            self.findAndClickJS("id", "contains", "isCurrent")

        cmd = lambda : self.findClosestRelativesJS(self.TXT, self.MATCH, 'From', "element", "match", "select", "legend")
        cmd()
        self.fillDropDown("relatives[0]", frmMonCont, cmd)
        self.fillDropDown("relatives[relatives.length-1]", frmYrCont, cmd)

        if not current:
            toMonCont, toYrCont = tuple(toDate.split(" "))
            cmd = lambda : self.findClosestRelativesJS(self.TXT, self.MATCH, 'To', "element", "match", "select", "legend")
            cmd()
            self.fillDropDown("relatives[0]", toMonCont, cmd)
            self.fillDropDown("relatives[relatives.length-1]", toYrCont, cmd)

        self.findAndClickJS("text", "match", "Save", elementTypeFilter="button")
        print("waiting 3 secs for page content to load ")
        t.sleep(3)
        return #self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)

    def do_skiils(self):
        # delete all prior
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Skills', self.ID, self.CONTAINS, 'delete', 'h2',
                                            srchLvlLmt=2)
        #self.click_all(deletes, delayBeforeEach=.1, timeLimitForEach=1)
        self.clickAllJS("relatives")

        for skill in self.skills:
            if "and" == skill[:3]:
                skill = skill[4:]
            if " and" == skill[:4]:
                skill = skill[5:]
            try:
                self.findClosestRelativesJS(self.TXT, self.MATCH, 'Skills', self.WHOLE, self.WHOLE, self.BUTTON)
            except:
                traceback.print_exc()
                h = 3
            #self.smartClick(element=addSkillBut, waitBeforeClicking=.7, checkNewPage=True)
            self.smartClickJS("relatives[0]")
            self.findFillMoveOn(self.ID, self.CONTAINS, 'skillName', skill)
            self.finalizeResumeSection()

    def fillSkills(self):
        # generate a list of skills using chat GPT here
        for skill in self.skills:
            self.findFillEnter(self.ID, self.CONTAINS, 'new-skill-form', skill)

    def do_work_exp(self):
        # delete all prior
        self.findClosestRelativesJS(self.TXT, self.CONTAINS, 'Work experience', self.ID, self.CONTAINS,
                                            'delete', "h2", srchLvlLmt=2)
        #self.click_all(deletes)
        self.clickAllJS("relatives")

        for job in self.jobs:
            try:
                self.findClosestRelativesJS(self.TXT, self.MATCH, 'Work experience', self.WHOLE, self.WHOLE, self.BUTTON)
            except:
                traceback.print_exc()
                h = 3
            self.smartClickJS("relatives[0]")
            self.handleJob(job)


    def do_edu(self):
        # delete all prior
        deletes = self.findClosestRelativesJS(self.TXT, self.MATCH, 'Education', self.ID, self.CONTAINS,
                                            'delete', 'h2', srchLvlLmt=2)
        #self.click_all(deletes)
        self.clickAllJS("relatives")

        for edu in self.edus:
            self.findClosestRelativesJS(self.TXT, self.MATCH, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)
            #self.smartClick(element=addEduBut, waitBeforeClicking=.7, checkNewPage=True)
            self.smartClickJS("relatives[0]")
            self.handleEdu(edu)


    def process_job_file(self, filename):
        jobFile = open(filename, "r")
        infoDict = {}
        for subject in ['title', 'comp', 'compType', 'cityState', 'current', 'fromDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(jobFile), self.nextNonBlankLine(jobFile).strip()

        # read the rest of the lines, that'll be the description
        _, rawDesc = self.nextNonBlankLine(jobFile), jobFile.read().strip()
        '''mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()'''

        mygpt = myGPT2("job_desc_prompts2.txt", self.jobTitle, self.JobDescriptionText, infoDict['title'],
                       infoDict['compType'], rawDesc, infoDict['title'], infoDict['compType'])

        doAgain = True
        while doAgain:
            jobDesc = mygpt.sendAll().split("Here are the 3 points:")[1].strip()
            doAgain = mygpt.need_redo
        infoDict['desc'] = jobDesc

        return infoDict

    def process_job_record(self, record):
        infoDict = {}
        for subject in [('title', "JobTitle"), ('comp', "CompanyName"), ('compType', "CompanyType"),
                        ('cityState', "areaSpec"),
                        ('current', "currentPosition"), ('fromDate', "From"), ('toDate', "To"), ("country", "country")]:
            infoDict[subject[0]] = record[subject[1]]

        # read the rest of the lines, that'll be the description
        rawDesc = record["Description"]
        '''mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()'''

        mygpt = myGPT2("job_desc_prompts2.txt", self.jobTitle, self.JobDescriptionText, infoDict['title'],
                       infoDict['compType'], rawDesc, infoDict['title'], infoDict['compType'])

        doAgain = True
        while doAgain:
            jobDesc = mygpt.sendAll().split("Here are the 3 points:")[1].strip()
            doAgain = mygpt.need_redo
        infoDict['desc'] = jobDesc

        return infoDict

    def process_edu_file(self, filename):
        eduFile = open(filename, "r")
        infoDict = {}
        for subject in ['educationLevel', 'fieldOfStudy', 'school', 'cityState', 'current', 'frmDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(eduFile), self.nextNonBlankLine(eduFile).strip()

        return infoDict

    def process_edu_record(self, record):
        infoDict = {}
        for subject in [('educationLevel', "level"), ('fieldOfStudy', "fieldOfStudy"), ('school', "SchoolName"),
                        ('cityState', "areaSpec"),
                        ('current', "currentlyEnrolled"), ('frmDate', "From"), ('toDate', "To"),
                        ("country", "country")]:
            infoDict[subject[0]] = record[subject[1]]

        return infoDict

    def load_jobs(self):
        self.jobs.clear()

        for jobRec in self.jobRecords:
            if self.cur_profile["jobN"] is None or jobRec["jobNum"] in self.cur_profile["jobN"]:
                self.jobs.append(self.process_job_record(jobRec))

        '''files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)

        if self.cur_profile["jobN"] is None:  # then doing all job files
            jobFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]
        else:
            jobFiles = [self.MY_PATH + self.dataPath + f"Job{n}.txt" for n in self.cur_profile["jobN"] ]

        for jobFile in jobFiles:
            self.jobs.append(self.process_job_file(jobFile))'''

    def load_edu(self):
        self.edus.clear()
        for eduRec in self.eduRecords:
            if self.cur_profile["eduN"] is None or eduRec["eduNum"] in self.cur_profile["eduN"]:
                self.edus.append(self.process_edu_record(eduRec))
        '''files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)

        if self.cur_profile["eduN"] is None:
            eduFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Edu\d+\.txt$', f)]
        else:
            eduFiles = [self.MY_PATH + self.dataPath + f"Edu{n}.txt" for n in self.cur_profile["eduN"]]

        for eduFile in eduFiles:
            self.edus.append(self.process_edu_file(eduFile))'''

    def deleteAllPrevJobs(self):
        t.sleep(1)
        delButs = self.driver.find_elements("xpath", "//*[contains(@id, 'delete')]")
        for delB in delButs:
            self.smartClick(element=delB)

            if delB == delButs[-1]:
                # only want to do this after deleting the last job.  If we didn't have to delete anyting, then don't need
                # to click on this "Add another" button
                self.addAnother()

    def fillPrevJobsInfo(self):
        # Adding a job
        for job in self.jobs:
            self.handleJob(job)

            self.finalizeResumeSection()

            # check if there are still more job files to process
            if job != self.jobs[-1]:
                self.addAnother()

    def handleJob(self, job: dict):
        title, comp, _, cityState, current, fromDate, toDate, country, desc = tuple(job.values())
        current = "y" in current.lower()

        # Job Title
        self.findFillMoveOn(self.ID, self.CONTAINS, 'jobTitle', title)

        # company name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'company', comp)

        # country location
        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON)
        #self.smartClick(element=chg_country_but)
        self.smartClickJS("relatives[0]")

        self.findClosestRelativesJS(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT)
        self.fillDropDown("relatives[0]", self.country )

        # city state
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        frmMonCont, frmYrCont = tuple(fromDate.split(" "))


        # current position
        if current:
            self.findAndClickJS("id", "contains", "isCurrent")

        cmd = lambda : self.findClosestRelativesJS(self.TXT, self.MATCH, 'From', "element", "match", "select", "legend")
        cmd()
        self.fillDropDown("relatives[0]", frmMonCont, cmd)
        self.fillDropDown("relatives[relatives.length-1]", frmYrCont, cmd)

        if not current:
            toMonCont, toYrCont = tuple(toDate.split(" "))
            cmd = lambda : self.findClosestRelativesJS(self.TXT, self.MATCH, 'To', "element", "match", "select", "legend")
            cmd()
            self.fillDropDown("relatives[0]", toMonCont, cmd)
            self.fillDropDown("relatives[relatives.length-1]", toYrCont, cmd)

        # description
        txtBoxPath = "//div[@role='textbox']"
        desc = desc.replace("- ", "")
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)  # need GPT
        self.execute("toFindAndFill.textContent")
        descEleText = self.getJsResult()

        while any([descPoint[2:] not in descEleText for descPoint in desc.split("\n")]):
            self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)

        # make bullets
        self.smartClickJS("toFindAndFill")
        send_keys('{VK_F12}')
        send_keys("^a")
        send_keys('{VK_F12}')
        t.sleep(1)
        self.openDevConsoleGuaranteed()
        #descEle.send_keys(Keys.CONTROL, "a")
        xp = "//button[@data-testid='insertUnorderedList']"
        #self.findAndClick(self.WHOLE, self.WHOLE, xp)
        self.findAndClickJS("whole", None, xp)

        self.findAndClickJS("text", "match", "Save", elementTypeFilter="button")
        print("waiting 3 secs for page content to load ")
        t.sleep(3)
        return #self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)

    def checkIfMoreQuestionsAppeared(self):
        #allPageQuestions, origQuestSet, questn = tup_ptr
        #nextQuestInd = allPageQuestions.index(questn) + 1
        self.execute("var nqi = qz.indexOf(questn) + 1 ;")
        #QsLeft = allPageQuestions[nextQuestInd:]
        #del allPageQuestions[nextQuestInd:]
        self.execute("var qzLeft = qz.splice(nqi) ;")
        #latestAllQs = set(self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
        #                                    indInList=self.ALL, txtCond="#$%^&*(KJH"))
        self.findAndClickJS("class", self.CONTAINS, 'Questions-item', self.ALL, varName="latestQz")
        #newQs = latestAllQs - origQuestSet
        self.execute("var newQz = latestQz.filter(element => !qz.includes(element));")
        #### ??? origQuestSet.clear()
        #### ??? origQuestSet.update(latestAllQs)
        #allPageQuestions.extend(newQs)
        #allPageQuestions.extend(QsLeft)
        self.execute("qz = qz.concat(newQz).concat(qzLeft) ;")

    def analyzeAndAnsQuestions(self):
        self.getLock()
        self.openDevConsoleGuaranteed()
        self.loadJS()
        self.findAndClickJS("class", self.CONTAINS, 'Questions-item', self.ALL, varName="qz")
        self.execute("qz.length")
        numQz = self.getJsResult(int)
        #allPageQuestions = self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
        #                                     indInList=self.ALL, txtCond="#$%^&*(KJH")


        self.execute("origQuestSet = new Set(qz);")
        if numQz > 0:
            self.execute("document.URL")
            url1 = self.getJsResult()
            # hit continue. Since no answers are chosen, this
            # wont be allowed and all the question error txt will appear
            self.findAndClickJS("text", "match", "Continue", elementTypeFilter="button")
            #self.findAndClick(self.TXT, self.MATCH, 'Continue', travelUp=1, waitBeforeClicking=.2)

            # if the url changed (meaning that our old responses were used)then just finish/return
            t.sleep(2)
            self.execute("document.URL")
            url2 = self.getJsResult()
            if url1 != url2:
                return  # nothing to do...questions already answered

            #for questn in allPageQuestions:
            q_i = 0
            while q_i < numQz:
                try:
                    ret = self.process_question(q_i)
                    if isinstance(ret, BadPost):
                        return ret
                    # after answering quesiton, see if any more pop up
                    self.checkIfMoreQuestionsAppeared()
                    self.execute("qz.length")
                    numQz = self.getJsResult(int)
                    self.MML.append(datetime.datetime.now())

                except:
                    traceback.print_exc()
                    h = 3
                q_i += 1

        return self.keepGoing()

    def checkIfQuestionAlreadyAnswered(self, type):
        if type == self.FreeResponse or type == self.FreeResponseLong:
            self.execute("ans_dict['inputBox'].getAttribute('value'); ")
            prevTxt = self.getJsResult()
            return len(prevTxt) > 0
        elif type == self.MultChoice:
            # check if already answered
            self.findAndClickJS("whole", None, '//*[@checked]', txtCond="&*(", findFrom="questn")
            res = self.getJsResult()
            return res != "null"
        elif type == self.DropDown:
            self.execute("var val = ans_dict['dropDown'].value")
            self.execute("val.length")
            res = self.getJsResult(int)
            return res > 0
        elif type == self.SelectApplicable or type == self.DateFill:
            return False
        else:
            return

    def ensureQualityOfDateRespAns(self, gptObj, questn, helpTxt, ans):
        qxpath = self.generate_full_xpath(questn)
        updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
        _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        while errorTxt is not None:
            ans = gptObj.sendFromFile("date_wrong_prompts.txt", helpTxt)
            self.fillMoveOn(answer_choices['inputBox'], ans)
            qxpath = self.generate_full_xpath(questn)
            updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
            _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)
        return ans

    def ensureQualityOfFreeRespAns(self, gptObj, qTxt, ans):
        _, errorTxt, _ = self.extractQuestionInfo(qTxt)

        while errorTxt is not None:
            ans = gptObj.sendFromFile("free_resp_choice_wrong_prompts.txt", errorTxt)
            self.fillMoveOn("ans_dict['inputBox']", ans)
            _, errorTxt, _ = self.extractQuestionInfo(qTxt)

        return ans

    def getTopChoiceScore(self, ans, answerChoices):
        choices_n_scores = [(ans_choice, self.jaccard_similarity(ans_choice, ans)) for ans_choice in
                            answerChoices]
        choices_n_scores.sort(key=lambda x: x[1], reverse=True)
        thresh = self.jaccard_similarity(ans + "~`*", ans)
        topChoice, topScore = choices_n_scores[0]
        return topChoice, topScore, thresh

    def ensureQualityOfMultChoiceAns(self, gptObj, answerChoices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answerChoices.split("\n"))
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt").split("The answer is:")[1]
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answerChoices.split("\n"))
        self.findAndClickJS("whole", None, "//input", txtCond="^&*", findFrom=f'ans_dict["{topChoice}"]', varName="inputEle")


        while self.execAndRet(lambda: self.execute( f'inputEle.checked' )) != 'true':
            self.smartClickJS(f'ans_dict["{topChoice}"]')
        return topChoice

    def ensureQualityOfSelectApplicableAns(self, gptObj, answerChoices, ans):
        answers = ans
        topChoiceScoreThresh = [self.getTopChoiceScore(answer, answerChoices.split("\n")) for answer in answers]
        while any(topScore < thresh for topChoice, topScore, thresh in topChoiceScoreThresh):
            answer = gptObj.sendFromFile("select_applicable_wrong_prompts.txt")
            answers = [thing.strip() for thing in answer.split("\n") if len(thing.strip()) > 0]
            topChoiceScoreThresh = [self.getTopChoiceScore(answer, answerChoices) for answer in answers]

        final_answers = []
        for topChoice, topScore, thresh in topChoiceScoreThresh:
            self.findAndClickJS("whole", None, "input", txtCond="^&*", findFrom=f'ans_dict["{topChoice}"]  ', varName="inputEle")
            while self.execAndRet(lambda: self.execute( 'inputEle.checked' )) != 'true':
                self.smartClickJS(f'ans_dict["{topChoice}"] ')
            final_answers.append(topChoice)
        return str(final_answers)

    def ensureQualityOfDropDownAns(self, gptObj, answerChoices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answerChoices.split("\n"))
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt")
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answerChoices)
        # print(f"b4  *{answer_choices['dropDown'].get_attribute('value')}*")
        self.fillDropDown("ans_dict['dropDown']", topChoice)

        # DO WE NEED TO MAKE SURE HERE LIKE WE DO IN A LOOP IN THE MULT CHOICE VERSION ???? !!!!!!

        return topChoice

    def relevantSubStr(self, substr, fullStr):
        maxLen = int(len(substr) * 1.5)
        # Escape any special characters in substr
        escaped_substr = re.escape(substr.lower())
        # Construct the regular expression pattern
        pattern = rf'^(?!.{{{maxLen},}})(.*[^a-zA-Z])?{escaped_substr}([^a-zA-Z].*)?$'
        # Check if the string matches the pattern
        return bool(re.match(pattern, fullStr))

    def checkIfAPreMadeAnswerFits(self, questn_txt, type):
        detailKeysOrdrd = list(self.details.keys())
        detailKeysOrdrd.sort(key=lambda x: len(x), reverse=True)
        ourAns = None
        for detKey in detailKeysOrdrd:
            if self.relevantSubStr(detKey, questn_txt.lower()):
                ourAns = self.details[detKey]
                break
        if ourAns is not None:
            if type == self.DropDown:
                self.fillDropDown("ans_dict['dropDown']", ourAns)
            elif type == self.FreeResponse:
                self.fillMoveOn("ans_dict['inputBox']", ourAns)
            else:
                return False
            return True
        else:
            return False

    def process_question(self, q_i):  # //div[contains(@class, 'Questions-item')]
        # Do we even have to do this question?
        self.execute(f"var questn = qz[{q_i}]")
        self.execute('questn.querySelector("legend, label").textContent')
        txt = self.getJsResult()
        #txt = questn.text
        if '(optional)' in txt:
            return

        questn_txt, errorTxt, type = self.extractQuestionInfo(txt)

        if isinstance(type, BadPost):
            return type

        if self.checkIfQuestionAlreadyAnswered( type):
            return

        if self.checkIfAPreMadeAnswerFits(questn_txt, type):
            return

        helpTxt = "Answer as concisely and in as natural a way as possible"
        if errorTxt is not None:
            helpTxt = errorTxt

        self.txt = questn_txt

        #  get ans back from chat GPT
        ans = None
        final_answer = None
        if type == self.FreeResponse or type == self.FreeResponseLong:
            # get chat GPT help with free response question
            mygpt = myGPT2("free_response_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                           str(self.details), self.lifeSummary, questn_txt, helpTxt, self.zip, self.phone_num,
                           self.email, version=1)
            ans = mygpt.sendAll()
            self.fillMoveOn("ans_dict['inputBox']", ans)

            final_answer = self.ensureQualityOfFreeRespAns(mygpt, questn_txt, ans)

        elif type == self.DateFill:
            # get chat GPT help with free response question
            mygpt = myGPT2("date_fill_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                           questn_txt, self.today_mmddyyy(), helpTxt, version=1)
            ans = mygpt.sendAll()
            month, day, year = tuple(ans.split("-"))
            # self.fillMoveOn(answer_choices['inputBox'], ans)
            self.findAndClickJS("aria-label", "contains", "Choose a date", findFrom="questn")

            #  select month
            self.findAndClickJS("aria-label", "contains", "Month select", findFrom="questn", varName="monSelect")
            self.fillDropDown("monSelect", month)

            # seelct year
            self.findAndClickJS("aria-label", "contains", "Month select", findFrom="questn", varName="yrSelect")
            self.fillDropDown("yrSelect", year)

            self.findAndClickJS("text", "match", day, findFrom="questn")


        elif type == self.MultChoice:
            # get chat GPT help
            self.execute("var arrOfKeys = Object.keys(ans_dict)")
            self.execute('arrOfKeys.join("{nl}")')
            answerChoices = self.getJsResult().replace("{nl}", "\n")
            mygpt = myGPT2("mult_choice_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                           questn_txt, answerChoices, helpTxt, version=1)
            ans = mygpt.sendAll().split("The answer is:")[1].strip()

            final_answer = self.ensureQualityOfMultChoiceAns(mygpt, answerChoices, ans)

        elif type == self.SelectApplicable:
            # get chat GPT help
            self.execute("var arrOfKeys = Object.keys(ans_dict)")
            self.execute('arrOfKeys.join("{nl}")')
            answerChoices = self.getJsResult().replace("{nl}", "\n")
            mygpt = myGPT2("select_applicable_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                           questn_txt, answerChoices, helpTxt, version=1)
            ans = mygpt.sendAll()
            ans_list = [thing.strip() for thing in ans.split("\n") if len(thing.strip()) > 0]

            final_answer = self.ensureQualityOfSelectApplicableAns(mygpt, answerChoices, ans_list)


        elif type == self.DropDown:
            self.execute("var arrOfKeys = Object.keys(ans_dict['answers'])")
            self.execute('arrOfKeys.join("{nl}")')
            answerChoices = self.getJsResult().replace("{nl}", "\n")
            # get chat GPT help
            mygpt = myGPT2("drop_down_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                           questn_txt, str(self.details), self.lifeSummary,
                           answerChoices,
                           helpTxt, version=1)
            ans = mygpt.sendAll()

            #  break here because need to verify that dropdwn is actually the corrct element to send answer to
            final_answer = self.ensureQualityOfDropDownAns(mygpt, answerChoices, ans)

        self.prev_questions.append({"Question": questn_txt, "Answer": final_answer})

    def extractQuestionInfo(self, txt):

        #ans_dict = {
            # format =  "Yes": <obj>
            # format =  "No": <obj>
        #}
        self.execute("var ans_dict = {};")
        intermediate_ans_list = []
        questionText = ""
        # determine type  //*[@aria-label="Day and time option"]
        type = self.determine_question_type(txt)

        if isinstance(type, BadPost):
            return None, None, type


        # get error text
        self.findAndClickJS("id", "contains", "errorText", txtCond="^&*", findFrom="questn", varName="errObj")
        self.execute("errObj.textContent")
        errorTxt = self.getJsResult()

        if errorTxt == "undefined":
            self.findAndClickJS("whole", None,"//span[@role='alert']", txtCond="$%^&*()", findFrom="questn", varName="et" )
            self.execute("et.textContent")
            errorTxt = self.getJsResult()


        reduceCode = """ ans_list_inter.reduce((acc, obj) => 
                        {
                            if (obj.textContent && obj.textContent.length > 0) {
                                acc[obj.textContent] = obj;
                            }
                            return acc;
                        }, {});"""

        # get answer choices & question text
        try:
            if type == self.FreeResponse or type == self.FreeResponseLong or type == self.DateFill:
                self.findAndClickJS("whole", None, ["//input", "//textarea"], findFrom="questn", varName="ib")
                self.execute("ans_dict.inputBox = ib;")
                self.execute("ib")
                res = self.getJsResult()

                if res == 'null':
                    type = self.Bad

                self.findAndClickJS("whole", "whole", "//label", findFrom="questn", txtCond="*()", varName="txtRoot")
                self.execute("txtRoot.textContent")

                rootText = self.getJsResult()
                questionText = {self.FreeResponse: rootText,
                                self.DateFill: rootText,
                                self.FreeResponseLong: rootText.split("\n")[-1].replace("\"", "")}[type]

            elif type == self.MultChoice:
                self.findAndClickJS("whole", None, "//label", findFrom="questn", indexInList=self.ALL, varName="ans_list_inter")

                self.execute("ans_dict =" + reduceCode)
                self.findAndClickJS("whole", None, "//legend", findFrom="questn", txtCond="**(J", varName="qt")
                self.execute("qt.textContent")
                questionText = self.getJsResult()

            elif type == self.DropDown:
                self.findAndClickJS("whole", None, "//option", findFrom="questn", indexInList=self.ALL, varName="ans_list_inter")
                self.execute("ans_dict['answers'] =" + reduceCode)
                self.findAndClickJS("whole", None, "//select", findFrom="questn", varName="sel")
                self.execute("ans_dict['dropDown'] = sel ;")
                self.findAndClickJS("whole", None, "//label", findFrom="questn", txtCond="&*(", varName="lbl")
                self.execute("lbl.textContent")
                questionText = self.getJsResult()

            elif type == self.SelectApplicable:
                self.findAndClickJS("whole", None, "//label", findFrom="questn", indexInList=self.ALL, varName="ans_list_inter")
                self.execute("ans_list_inter.shift()")
                intermediate_ans_list.pop(0)
                self.execute("ans_dict['answers'] =" + reduceCode)
                self.findAndClickJS("whole", None, "//label", findFrom="questn", txtCond="**(J", varName="qt")
                self.execute("qt.textContent")
                questionText = self.getJsResult()

            elif type == self.Bad:
                self.findAndClickJS("whole", None, "//label", findFrom="questn", txtCond="**(J", varName="qt")
                self.execute("qt.textContent")
                questionText = self.getJsResult()

        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()
            still = True
            while still:
                t.sleep(1)

        if "(optional)" in questionText:
            type = self.Bad

        return questionText, errorTxt, type

    def redirectAndSkip(self, message):
        self.execute('window.location.href = "https://www.google.com"')
        t.sleep(1)
        send_keys("{ENTER}")
        return BadPost(message)

    def determine_question_type(self, txt):

        #qChild = self.get_child(questn, 1, 1)
        self.execute("var qChild = questn.children[0]")
        self.execute("qChild")
        res = self.getJsResult()
        if res == "undefined":
            return self.Bad

        #num = self.num_children(qChild)
        #self.execute("questn.children.length")
        #num = self.getJsResult(int)
        #self.findAndClickJS("aria-label", "match", 'Day and time option', findFrom="questn", indexInList=self.ALL, varName="listOfBad")
        #listOfBad = self.findAndClick('@aria-label', self.MATCH, 'Day and time option', findFrom=questn,
        #                              indInList=self.ALL)
        #self.execute("listOfBad.length")
        #badLen = self.getJsResult(int)
        #self.execute("questn.children[0].children[1].children.length")
        #kidLen = self.getJsResult(int)


        #if badLen > 0 or self.num_children(self.get_child_complex(questn, "1/2")) == 0:
        '''if badLen > 0 or kidLen == 0:
            # then it's a question we don't want
            if "upload" in txt:
                return self.redirectAndSkip("bad question... not dealing with it")
            else:
                return self.Bad
        '''
        if self.execAndRet(lambda: self.findAndClickJS("whole", "whole", "//input | //select | //textarea", findFrom="questn", txtCond="^&*(", varName="inp"),
                    varName="inp") != "undefined":
            #  also contains input, find out what kind of input (radio or checkbox)
            self.execute("inp.getAttribute('type') || inp.getAttribute('role') || inp.tagName")
            typeOfInput = self.getJsResult()
            return {"radio": self.MultChoice, "checkbox": self.SelectApplicable,
                    "number": self.FreeResponse, "text": self.FreeResponse,
                    "combobox": self.DropDown }.get(typeOfInput, self.Bad )
            # still need:
            #
            #  self.FreeResponseLong
            #  self.DateFill
            #  self.DropDown
            #
        t = 0
        if self.execAndRet(lambda: self.findAndClickJS("whole", None, "//div[@role='group']", findFrom="questn", txtCond="^&*(")
                        ) != "undefined":
            return self.redirectAndSkip("This was the group... analzye and see..")

        elif self.execAndRet( lambda: self.findAndClickJS("id", "contains", "FileUpload", findFrom="questn", txtCond="^&*(")
                        ) != "undefined":
            # redirect to google because that's the environment that tells us we need to skip this post
            return self.redirectAndSkip("They wanted us to upload a file... fuck that.. not dealing with it")

        elif self.execAndRet(lambda: self.findAndClickJS("whole", None, "//textarea", findFrom="questn", txtCond="^&*(")
                        ) != "undefined":
            return self.FreeResponseLong

        elif self.execAndRet(lambda: self.findAndClickJS("whole", None, "//input", findFrom="questn", txtCond="^&*(")
                        ) != "undefined":
            if self.execAndRet(lambda: self.findAndClickJS("whole", None, "//button", findFrom="questn", txtCond="^&*(")
                            ) != "undefined":
                return self.DateFill
            else:
                return self.FreeResponse

        elif self.execAndRet(lambda: self.findAndClickJS("whole", None, "//select", findFrom="questn", txtCond="^&*(")
                        ) != "undefined":
            return self.DropDown
        else:
            return self.Bad

    def do_cover_letter(self):

        # selection = self.findAndClick(self.ID, self.CONTAINS,  'write-cover-letter-selection-card')
        #cl = self.findAndClick(self.WHOLE, self.WHOLE, "//div[@data-testid='CoverLetterRadioCard']", txtCond="asdfas")
        self.findAndClickJS("whole", None, "//div[@data-testid='CoverLetterRadioCard']", varName="cl")

        #if cl is not None:
        #    cl.click()

        self.findFillMoveOn(self.WHOLE, self.WHOLE, self.TXTAREA, self.coverLetter)

        self.findAndClickJS("text", "match", ['Update', 'Review your application'], elementTypeFilter="button")
        return

    def addAnother(self):
        self.findAndClickJS("text", "contains", "Add another", elementTypeFilter="button")
        #self.findAndClick(self.TXT, self.CONTAINS, 'Add another', travelUp=1)

    def finalizeResumeSection(self):
        self.findAndClickJS("text", "match", "Save", elementTypeFilter="button")
        print("waiting 3 secs for page content to load ")
        t.sleep(3)
        #self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)

    def nextResumeSection(self):
        self.findAndClickJS("text", "match", "Save and continue", elementTypeFilter="button")
        #self.findAndClick(self.TXT, self.MATCH, 'Save and continue', travelUp=1)

    def split_into_substrings(self, s):
        # Split the string and filter out empty strings, then extend to ensure 3 elements
        parts = [x if x else None for x in s.split(' ')] + [None] * 2
        return parts[0], parts[1], parts[2]

    def getProfileGen(self):
        infinite_iterator = itertools.cycle(self.profiles)
        for profile in infinite_iterator:
            self.home_url = profile["home"]
            yield profile

    def load_startup_info(self, info):
        # purpose of '_' is to skip the explanation of the next line/section
        # nextOccrance(self,file_handler, substr, delim="\t", after=""):
        try:
            self.MY_PATH = "Users\\" + f"{info['FirstName']} {info['LastName']} {info['id']}" + "\\"
            homeInfos = info["homePage"].split("\n")
            for info_h in homeInfos:
                info_h = info_h.strip("\r")
                h, j, e = self.split_into_substrings(info_h)
                self.profiles.append({"home": h,
                                      "eduN": [int(n) for n in e.split(",")] if e else e,
                                      "jobN": [int(n) for n in j.split(",")] if j else j})
            self.profile_generator = self.getProfileGen()
            self.cur_profile = next(self.profile_generator)

            self.home_url_pattern = info["homePagePattern"]
            self.chrome_profile = info["ProfilePath"]
            self.user_id = int(info["id"])
            self.applicationsLeft = info["AppsLeft"]
            self.firstName = info["FirstName"]
            self.lastName = info["LastName"]
            self.phone_num = info["PhoneNumber"]
            self.email = info["IndeedEmail"]
            self.addr = info["address"]
            self.areaSpec = info["areaSpec"]
            self.country = info["country"]
            self.zip = info["zip"]
            self.lifeSummary = info["LifeSummary"]
            self.avoid = info["avoid"]

        except:
            return

    def load_life_summary(self):
        # purpose of '_' is to skip the explanation of the next line/section
        try:
            self.setDetails()
            # self.saveUserInDB()
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()

    def setDetails(self):
        c, s = tuple(self.areaSpec.split(","))
        self.details = {"name": f"{self.firstName} {self.lastName}",
                        "first name": self.firstName,
                        "last name": self.lastName,
                        "number": self.phone_num, "phone": self.phone_num,
                        "phone number": self.phone_num.replace("(", "").replace(")", "").replace(" ", "").replace("-",
                                                                                                                  ""),
                        "email": self.email,
                        "address": self.addr,
                        "city": c, "state": s.strip(), "country": self.country,
                        "zip": self.zip, "postal code": self.zip}

    def jobContainsForbiddenCharacteristics(self):
        mygpt = myGPT2("avoid_job_characteristics_prompts2.txt", self.jobDescriptionText)
        mygpt.sendAll()
        # get the avoidance qualities
        # avoidFile = open(self.MY_PATH + self.dataPath + "AvoidTheseJobCharacteristics.txt", 'r')
        # avoidLines = avoidFile.readlines()
        for avoidLine in self.avoid.split("\n"):
            if len(avoidLine.strip()) == 0:
                continue
            # prompt = f'''Does this job match this characteristic:\n{avoidLine}\n\nif not, then just say "no",
            # if so, then say "yes" and also include the portion of the job description that
            # matches the above characteristic.'''

            prompt = f'''{avoidLine} If the answer is no, then reply "NO" and say nothing else.  If the answer is yes, 
            then reply "YES" and then also tell me the portion of the job description that made you say "YES"'''
            ans = mygpt.send(prompt).lower()
            if "yes" in ans:
                self.reportAction("CHAT GPT SAID: " + ans, False)
                return True

        return False

    def getPositionInfo(self):
        cName = "css-1ioi40n e19afand0"
        self.findAndClickJS("class", "match", cName, txtCond="YGUHJI^&*(", varName="compNameEle")
        self.execute("compNameEle.textContent")
        self.companyName = self.getJsResult()

        self.findAndClickJS("class", "contains", "jobsearch-JobInfoHeader-title", txtCond="YGUHJI^&*(", varName="h1_ele")
        self.execute("h1_ele.textContent")
        self.jobTitle = self.getJsResult()

        jde = "jobDescElement"
        self.findAndClickJS("id", "match", "jobDescriptionText", txtCond="%^G", varName=jde)
        self.execute(f"{jde}.textContent")
        self.jobDescriptionText = self.getJsResult()

    def generateHeadline(self):
        mygpt = myGPT2("headline_prompts2.txt", self.JobDescriptionText)

        doAgain = True
        while doAgain:
            self.headline = mygpt.sendAll().split("The headline is:")[1].strip().strip(".")
            doAgain = mygpt.need_redo

    def generateCL(self):
        '''mygpt = myGPT("cover_letter_prompts.txt", self.jobTitle, self.companyName,
                      self.JobDescriptionText, self.firstName, self.lastName,
                      self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                      self.email, self.cityState, self.today() )
        self.coverLetter = mygpt.sendAll()'''

        mygpt = myGPT2("cover_letter_prompts2.txt", self.jobTitle, self.companyName,
                       self.JobDescriptionText, self.firstName, self.lastName,
                       self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                       self.email, self.areaSpec, self.today())

        doAgain = True
        while doAgain:
            self.coverLetter = mygpt.sendAll()
            doAgain = mygpt.need_redo

    def generateSummary(self):
        '''mygpt = myGPT("summary_prompts.txt", self.coverLetter, self.firstName)
        self.resumeSummary = mygpt.sendAll()'''

        mygpt = myGPT2("summary_prompts2.txt", self.coverLetter, self.firstName)

        doAgain = True
        while doAgain:
            self.resumeSummary = mygpt.sendAll()
            doAgain = mygpt.need_redo

    def generateSkills(self):
        '''mygpt = myGPT("skills_prompts.txt", self.JobDescriptionText, self.lifeSummary)
        skillsStrList = mygpt.sendAll()
        self.skills2 = skillsStrList.split(",")'''

        # initial skill list generation
        mygpt = myGPT2("skills_prompts2.txt", self.jobTitle, self.JobDescriptionText, self.lifeSummary)

        doAgain = True
        while doAgain:
            skillsStrList2 = mygpt.sendAll()
            doAgain = mygpt.need_redo

        firstTry = skillsStrList2
        skillsStrList2 = skillsStrList2.split("END_LIST")[0].strip().strip(";;")
        skillsStrList2 = skillsStrList2.replace("Here is the combined list:", "").strip().strip(".")
        intermediate_skills = skillsStrList2.split(";;")

        # skill list cleaning
        mygpt = myGPT2("skills_prompts_cleaning.txt", self.jobTitle, str(intermediate_skills), version=1)
        skillsStrList2 = mygpt.sendAll()
        secTry = skillsStrList2
        skillsStrList2 = skillsStrList2.split("END_LIST")[0].strip().strip(";;")
        skillsStrList2 = skillsStrList2.replace("Here is the revised list:", "").strip().strip(".").strip("\"").strip()
        self.skills = skillsStrList2.split(";;")
        self.tries.append({"1": firstTry, "2": secTry})

    def run(self):
        self.start_up()

        input("Press enter when you have signed in.")

        # for each page, process the job openings
        self.process_job_openings()


class StateMachine:
    def __init__(self, helper: PyAutoWrap):
        self.helper = helper
        self.validate_files("States.txt", "ExpectedEnvironments.txt", "StateTransitions.txt")
        self.states = self.load_states("States.txt")
        self.expected_environments = self.load_environments("ExpectedEnvironments.txt")
        self.transitions = self.load_transitions("StateTransitions.txt")
        self.current_state = self.states[0]
        self.prev_state = None

    def validate_files(self, states_file, expected_environments_file, state_transitions_file):
        # Helper function to read and clean lines from a file
        def read_clean_lines(filename, dirty=False):
            with open(filename, 'r') as f:
                lines = f.readlines()
            if dirty:
                return [line for line in lines if line.strip() and not line.strip().startswith("//")]
            return [line.strip() for line in lines if line.strip() and not line.strip().startswith("//")]

        # Read and clean lines from each file
        states = set(read_clean_lines(self.helper.configPath + states_file))
        expected_environments = set(read_clean_lines(self.helper.configPath + expected_environments_file))
        state_transitions_lines = read_clean_lines(self.helper.configPath + state_transitions_file, dirty=True)

        # Extract states and environments from state_transitions_lines
        state_transitions_states = set()
        state_transitions_environments = set()
        transFuncsMentioned = set()
        helpersAttributes = set(dir(self.helper))
        for line in state_transitions_lines:
            if "--" in line:
                line = line.replace("-->", "--")
                state1, func, state2 = line.split("--")
                transFuncsMentioned.add(func.strip().replace("()", ""))
                if 'default' not in state1:
                    state_transitions_states.add(state1.strip())
                state_transitions_states.add(state2.strip())
            elif line == line.lstrip():  # Lines without leading blanks are environments
                state_transitions_environments.add(line.strip())
            else:  # Indented lines without '--' are states
                state_transitions_states.add(line.strip())

        # Perform the checks
        missing_states_in_transitions = states - state_transitions_states
        extra_states_in_transitions = state_transitions_states - states - set(["default"])
        missing_environments_in_transitions = expected_environments - state_transitions_environments
        extra_environments_in_transitions = state_transitions_environments - expected_environments

        funcsNotDefined = transFuncsMentioned - helpersAttributes

        sep = '\n\t'
        if missing_states_in_transitions:
            print(f"States missing in {state_transitions_file}:{sep}{sep.join(missing_states_in_transitions)}")
        if extra_states_in_transitions:
            print(
                f"Extra states in {state_transitions_file} not found in {states_file}:{sep}{sep.join(extra_states_in_transitions)}")
        if missing_environments_in_transitions:
            print(
                f"Environments missing in {state_transitions_file}:{sep}{sep.join(missing_environments_in_transitions)}")
        if extra_environments_in_transitions:
            print(
                f"Extra environments in {state_transitions_file} not found in {expected_environments_file}:{sep}{sep.join(extra_environments_in_transitions)}")
        if funcsNotDefined:
            print(
                f"Transition Functions mentioned in {state_transitions_file} but not defined in Helper:{sep}{sep.join(funcsNotDefined)}")

        if (extra_environments_in_transitions or missing_environments_in_transitions
                or extra_states_in_transitions or missing_states_in_transitions or
                funcsNotDefined):
            sys.exit()

    def load_states(self, filename):
        with open(self.helper.configPath + filename, "r") as f:
            return [line.strip() for line in f.readlines() if line[:2] != "//" and len(line.strip()) > 0]

    def load_environments(self, filename):
        with open(self.helper.configPath + filename, "r") as f:
            return [self.helper.escape_regex_special_chars(line.strip()) for line in f.readlines() if
                    line[:2] != "//" and len(line.strip()) > 0]

    def load_transitions(self, filename):
        transitions = {}
        with open(self.helper.configPath + filename, "r") as f:
            lines = f.readlines()
            env = None
            pending_states = []  # List to store states that are waiting for transition info
            for line in lines:
                line = line.strip()
                prepped_line = self.helper.escape_regex_special_chars(line)
                if line[:2] == "//" or len(line) == 0:
                    # Skip empty lines and commented out lines
                    continue
                if prepped_line in self.expected_environments:
                    env = prepped_line
                    pending_states = []  # Reset pending states for a new environment
                elif "--" not in line:
                    # This line contains only a state without transition info
                    pending_states.append(line)
                else:
                    state, func, next_state = line.split("--")
                    state = state.strip()
                    func = func.strip("() ")
                    next_state = next_state.strip("-> ")
                    if env not in transitions:
                        transitions[env] = {}
                    # Apply the transition to the current state
                    transitions[env][state] = (func, next_state)
                    # Apply the transition to all pending states
                    for pending_state in pending_states:
                        transitions[env][pending_state] = (func, next_state)
                    # Clear the list of pending states
                    pending_states = []
        return transitions

    def envIsValid(self, environment):
        for pattern in sorted(self.expected_environments, key=len, reverse=True):
            if re.match(pattern.lower(), environment.lower()):
                return pattern
        # equivalent:
        # return next( (pattern for pattern in sorted(self.expected_environments, key=len, reverse=True)
        #            if re.match(pattern.lower(), environment.lower()) ) , None )
        return None

    def envNextTrans(self, environment):
        # here next is taking in 2 args: 1) a generator and 2) a defualt value for gen if empty
        return next((pattern for pattern in sorted(self.transitions.keys(), key=len, reverse=True)
                     if re.match(pattern.lower(), environment.lower())), None)

    def transition(self, environment):
        t.sleep(1)
        envPattern = self.envIsValid(environment)
        if not envPattern:
            print(f"Unexpected environment: {environment}")
            self.waitForever()
            return

        next_state = None
        # checking that the transition file as made properly
        if self.envNextTrans(environment) is not None:
            if self.current_state in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern][self.current_state]
            elif "default" in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern]["default"]
            else:
                print(f"No transition for state {self.current_state} and env {environment}")

            try:
                if "default" == next_state.strip():
                    next_state = self.current_state
            except:
                pass

            self.helper.reportAction(f"Calling function: {funcName}() in environment: {environment}", False)
            funcResult = self.executeFunc(funcName)
            # need to check that we accomplished what we wanted to accomplish with this function
            if isinstance(funcResult, StartFromTop):
                self.helper.reportAction(f"Transitioning  STATE from {self.current_state} BACK TO {self.prev_state}",
                                         False)
                self.current_state = self.prev_state
            else:
                self.helper.reportAction(f"Transitioning  STATE from {self.current_state} to {next_state}", False)
                self.prev_state = self.current_state
                self.current_state = next_state

        else:
            print(f"No transition defined for environment: {environment}")
            self.waitForever()

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        self.helper.getLock()
        method_to_call()
        self.helper.releaseLock()
        return

    def waitForever(self):
        still = True
        while still:
            t.sleep(1)

    def run(self):
        while True:
            env = self.helper.getCurrentEnv()
            if env == "exit":
                break
            self.transition(env)


'''def loadUsersFromDB():
    emailCol = "IndeedEmail"
    passCol = "IndeedPass"

    checker_query = """SELECT * FROM users WHERE AppsLeft > ? AND Active = ?"""


    values = (0, "T")
    conn = sqlite3.connect('IndHelperDB.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()


    cursor.execute(checker_query, values)

    # Fetch one record, if it exists
    allRecords = cursor.fetchall()

    # task1:  get all the records from the Job table that have the same userID as each of the records in allRecords
    # task2:  get all the records from the Edu table that have the same userID as each of the records in allRecords
    # task3:  return a data structure for which index 0 is a tuple containing the first record in allRecords, index 1 is
    #         all the records from task2 that match the first records in allRecords, index 2 is all the records from the
    #         task3 that match the first record in allRecords.

    return allRecords'''


def loadUsersFromDB():
    checker_query = """SELECT * FROM users WHERE AppsLeft > ? AND Active = ?"""

    values = (0, "T")
    conn = sqlite3.connect('IndHelperDB.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(checker_query, values)
    allRecords = cursor.fetchall()

    user_data = []

    for record in allRecords:
        userID = record["id"]

        # Task 1: Get all the records from the Job table that have the same userID
        job_query = """SELECT * FROM Job WHERE userID = ?"""
        cursor.execute(job_query, (userID,))
        job_records = cursor.fetchall()

        # Task 2: Get all the records from the Edu table that have the same userID
        edu_query = """SELECT * FROM Edu WHERE userID = ?"""
        cursor.execute(edu_query, (userID,))
        edu_records = cursor.fetchall()

        # Task 3: Construct the data structure
        user_data.append({"mainInfo": record, "edus": edu_records, "jobs": job_records})

    conn.close()
    return user_data


def RunUser(user_to_run, masterRecords):
    while (True):
        try:
            sm = StateMachine(IndeedHelper(user_to_run, masterRecords["milestoneList"]))
            masterRecords["sm_ref"] = sm
            sm.run()
        except Exception as e:
            try:
                sm.helper.reportAction(f"An error occurred: {e}", False)
                sm.helper.driver.quit()
            except:
                pass


def ReportStall(id):
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1)
    engine.say(f"Yoooooo bro id {id} is stalled")
    engine.runAndWait()


if __name__ == "__main__":
    # ih = IndeedHelper()
    # ih.run()
    usersToStart =loadUsersFromDB()  #470  578 6061  - nursing |  ext. (nursing specialist)  2188 email: nu_admissions@kennesaw.edu

    threads = []
    usr_records = {}

    for user in usersToStart:
        usr_records[user["mainInfo"]["id"]] = {"milestoneList": [datetime.datetime.now()], "sm_ref": None}
        thread = Thread(target=RunUser, args=(user, usr_records[user["mainInfo"]["id"]]))

        # Start the thread
        thread.start()

        # Append the threadto the list of threads
        threads.append(thread)

    while True:
        t.sleep(60)  # runs every mi`n
        try:
            for id, rec in usr_records.items():
                lastMilestone = rec["milestoneList"][-1]
                now = datetime.datetime.now()
                if (now - lastMilestone).seconds > 60 * 15:
                    if False:
                        ReportStall(id)
                    else:
                        rec["sm_ref"].helper.driver.quit()
                        rec["sm_ref"].helper.driver = None
                        rec["milestoneList"].append(datetime.datetime.now())
        except:
            h = 5
            traceback.print_exc()

    # for thread in threads:
    #    thread.join()

# ih = IndeedHelper()
# ih.run()

# https://www.indeed.com/jobs?q=&l=Remote&radius=35&start=10&pp=gQAPAAABiqZMUOEAAAACEQs_OgApAQAGAbWQDBy232HQyRWcqeGmhCw1EBtXt2H_3ngANxzAD_7ga50Vm1QAAA&vjk=5bb2ac5d6d7a7740