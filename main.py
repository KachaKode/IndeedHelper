# This is a sample Python script.

# GPT HELP:  https://chat.openai.com/c/aec09a74-238d-4f97-b49a-b6ca98e1d810

#Note  need to set up dummy chrome profile if you want browser to remember things

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import datetime
import traceback
import sys
import os, re
import sqlite3
import inspect
import time as t
#import openai
from myGPT import myGPT
from myGPT2 import myGPT as myGPT2
#from selenium import webdriver
#import webdriver_manager
#from webdriver_manager.chrome import ChromeDriverManager
import inspect


log = None


class BadPost(Exception):
    """Custom exception class for a specific error condition."""

    def __init__(self, message="An error occurred in my application"):
        self.message = message
        super().__init__(self.message)

class SeleniumWrap:

    def __init__(self, home_url, home_url_pattern, profile):
        self.chrome_profile = profile
        self.CONTAINS = "contains"
        self.MATCH = "matched"
        self.WHOLE = "whole"
        self.TXT = "text()"
        self.ID = "@id"
        self.CLASS = "@class"
        self.BUTTON = "//button"
        self.LABEL = "//label"
        self.INPUT = "//input"
        self.P = "//p"
        self.SELECT = "//select"
        self.LIST = "//ul"
        self.OPTION = "//option"
        self.LIST_ELEMENT = "//li"
        self.TXTAREA = '//textarea'
        self.LINK = '//a'
        self.ARIA_LABEL = '@aria-label'
        self.H1 = "//h1"
        self.SVG = "//svg"
        self.DELTA_WAIT = .2
        self.ALL = float('inf')
        self.home_url = home_url
        self.home_url_pattern = home_url_pattern

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
            line = self.nextNonBlankLine( file_handler )
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

    def process_list_element(self, listElement):
        listMemberElements = self.findAndClick(self.WHOLE, self.WHOLE, self.LIST_ELEMENT,
                                               indInList=self.ALL, findFrom=listElement)
        listMemberText = []
        for memElement in listMemberElements:
            listMemberText.append(memElement.text)
        return listMemberText

    def getListByTitle(self, titleText):
        listElements = self.findClosestRelatives(self.TXT, self.CONTAINS, titleText, self.WHOLE, self.WHOLE, self.LIST)
        return listElements[0]

    def clickButtonByText(self, buttonText, checkNewPage=False, checkNewTab=False, checkClosed=False, waitBeforeClicking=0):
        button = self.findClosestRelatives(self.TXT, self.CONTAINS, buttonText,
                                           self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=button, checkNewPage=checkNewPage, checkNewTab=checkNewTab,
                        checkClosed=checkClosed, waitBeforeClicking=waitBeforeClicking)

    def start_up(self):
        chrome_options = Options()
        chrome_options.add_argument(self.chrome_profile)
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.get(self.home_url)

    def goToTab(self, tab_num):
        # browser has already switched tabs but program still needs to switch
        all_tabs = self.driver.window_handles
        self.driver.switch_to.window(all_tabs[tab_num])


    def goToNewTab(self):
        # Get the current window handle
        current_handle = self.driver.current_window_handle

        # Get the list of all window handles
        all_handles = self.driver.window_handles

        # Find the index of the current window handle
        current_index = all_handles.index(current_handle)
        self.goToTab(current_index+1)

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
            self.smartClick(element= element, waitBeforeClicking=delayBeforeEach, timeLimit=timeLimitForEach)

    def closeDialogBox(self):
        dialogBox = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@role="dialog" and @aria-modal="true"]',
                                      txtCond="#$%^&*", timeLimit=.4)
        if dialogBox is not None:
            possCloseButs = dialogBox.find_elements(By.TAG_NAME, 'button')
            for button in possCloseButs:
                infoLabel = button.get_attribute("aria-label").lower()
                if 'close' in infoLabel:
                    self.smartClick(element=button)
                    self.reportAction("Closed Dialog")
                    return
            self.reportAction("Saw DIALOG but no close button (couldn't tell from label)")
        else:
            self.reportAction("No Dialog Found ")

    def clickChecker(self, element, checked, cond, ctrl):
        #check if condition is already met
        if cond():
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            checked[0] = True
            self.write("on line: " + str(inspect.currentframe().f_lineno))
        else:
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            try:  # if a new page is expected, then element might become unclickable
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                possibleExp = self.delayedClick(element, ctrl=ctrl)
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                if isinstance(possibleExp, ElementClickInterceptedException):
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    return possibleExp
            except:
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                # it's okay if an exception happens here.  Since we previously found the
                # element, we know it's only unclickable here because the page changed
                pass
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            t.sleep(self.DELTA_WAIT)
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            self.graduatedWait(cond)
            checked[0] = cond()
            if not checked[0]:
                raise Exception
            self.write("on line: " + str(inspect.currentframe().f_lineno))
        return checked[0]

    def clickAttempt(self, elementXpath, indInList , travelUp , txtCond , checkClosed,  checkNewPage,
                     checkNewTab , waitBeforeClicking , findFrom , waitBeforeFinding, url_at_start,
                     num_tabs_at_start, expectingPopUp, ctrl  ):

        t.sleep(waitBeforeFinding)

        # if looking for a list of all matches then don't need to click
        if indInList == self.ALL:
            matches = findFrom.find_elements('xpath', elementXpath)
            self.reportAction(f"returning {len(matches)} matches for {elementXpath}!")
            return matches


        elementList = findFrom.find_elements('xpath', elementXpath)
        #if len(elementList) == 0:
        #    return None
        try:
            element = elementList[indInList]
        except Exception as e:
            traceback.print_exc()
            h = 0

        numElementsOriginally = len(elementList)

        #the elemenet being disabled is the same as it not being there
        if element.get_attribute("disabled") is not None:
            return None

        # travel upwards if specified...
        for i in range(travelUp, 0, -1):
            element = self.get_parent(element)
        possibleExp = None

        if txtCond == '' or txtCond == element.text:
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            checked = [False]
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            while not checked[0]:
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                #account for the delay
                possibleExp = self.delayedClick(element, waitBeforeClicking, checked, ctrl)
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                if checkNewPage:
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    #cond = lambda: url_at_start != self.driver.current_url
                    def condFunc():
                        cur_url = self.driver.current_url
                        self.reportAction(f"checking:\n\tURL before:{url_at_start}\n\tURL after:{cur_url}")
                        return  url_at_start != cur_url
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    possibleExp = self.clickChecker(element, checked, condFunc, ctrl)
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                elif checkNewTab:
                    #cond = lambda: num_tabs_at_start != len(self.driver.window_handles)
                    def condFunc():
                        self.reportAction(f"checking:\n\ttabs before:{num_tabs_at_start}\n\ttabs after:{len(self.driver.window_handles)}")
                        return  num_tabs_at_start != len(self.driver.window_handles)
                    self.write("on line: " + str(inspect.currentframe().f_lineno))

                    possibleExp = self.clickChecker(element, checked, condFunc, ctrl)
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    if possibleExp and not isinstance(possibleExp, Exception) :
                        # go to ne tab
                        self.goToNewTab()
                elif checkClosed:
                    def condFunc():
                        updatedElementList = findFrom.find_elements('xpath', elementXpath)
                        self.reportAction(
                            f"checking:\n\t# elements before:{numElementsOriginally}\n\t# elements after:{len(updatedElementList)}")
                        return  len(updatedElementList) < numElementsOriginally
                    self.write("on line: " + str(inspect.currentframe().f_lineno))

                    possibleExp = self.clickChecker(element, checked, condFunc, ctrl)
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                self.write("on line: " + str(inspect.currentframe().f_lineno))


                #handle possible exception
                if isinstance(possibleExp, ElementClickInterceptedException):
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    return possibleExp
            self.write("on line: " + str(inspect.currentframe().f_lineno))

            self.reportAction(f"clicked {elementXpath} successfully!")
            self.write("on line: " + str(inspect.currentframe().f_lineno))

            if not expectingPopUp:  #if we aren't expecting a pop up, check for one and close it if it's there
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                self.closeDialogBox()
                self.write("on line: " + str(inspect.currentframe().f_lineno))
        else:
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            self.reportAction(f"found element {elementXpath} but did not click because text did not match: {txtCond}")
            self.write("on line: " + str(inspect.currentframe().f_lineno))
        self.write("on line: " + str(inspect.currentframe().f_lineno))
        return element

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


    def delayedClick(self, element, waitBeforeClicking=.05, checked=None, ctrl=False):
        self.write("on line: " + str(inspect.currentframe().f_lineno))
        try:
            #attempt to scroll element to center screen
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            t.sleep(max(waitBeforeClicking, .05))
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            if checked is not None:
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                checked[0] = True
                self.write("on line: " + str(inspect.currentframe().f_lineno))
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            if ctrl:
                action = ActionChains(self.driver)
                action.key_down(Keys.CONTROL).click(element).key_up(Keys.CONTROL).perform()
                self.goToNewTab()
            else:
                element.click()
            self.write("on line: " + str(inspect.currentframe().f_lineno))
        except Exception as e:
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            if isinstance(e, StaleElementReferenceException):
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                # If the exception is of type StaleElementReferenceException, re-raise it so it
                # propagates up the call stack and is ignored by clickChecker().  But we wanna catch
                # all other exceptions.
                raise
            if isinstance(e, ElementClickInterceptedException):
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                # If the exception is of type ElementClickInterceptedException, RETURN (not re-raise) the
                # exception so it propagates up and we don't change the state
                self.reportAction("Ran into ElementClickInterceptedException trying to click last found element")
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                checked[0] = e
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                return e
            if isinstance(e, ElementNotInteractableException):
                t.sleep(60*3)
                checked[0] = False
                return
            if isinstance(e, IndexError):
                raise
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            print("An error occurred:", e)
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            traceback.print_exc()
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            still = True
            while still:
                t.sleep(1)

    def delta_wait_4_click(self, elementXpath, spentWaiting, timeLimit):
        reportPause = spentWaiting[0] == 0
        t.sleep(self.DELTA_WAIT)
        spentWaiting[0] += self.DELTA_WAIT
        if spentWaiting[0] < timeLimit:
            if reportPause:
                self.reportAction(f"Paused trying to click. xpath: {elementXpath} ")
            return True
        else:
            self.reportAction(f"*\n*\n*\nTime OUT.  Spent {timeLimit} secs waiting already.\n*\n*\n*")
            return False

    def findAndClick(self, what, type, elementXpath, indInList=0, travelUp=0, timeLimit=10, txtCond = '', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0, expectingPopUp=False, elementType="*"  ):
        if isinstance(elementXpath, str):
            elementXpath = [elementXpath]
        root = ""
        if findFrom is None:
            findFrom = self.driver
        else:
            root = "."

        elementType = elementType.replace("//", "")

        _elementXpath = ""
        if type == self.CONTAINS:
            _elementXpath = f"{root}//{elementType}[contains({what}, '{elementXpath[0]}')]"
            for i in range(1, len(elementXpath)):
                _elementXpath += f" | {root}//{elementType}[contains({what}, '{elementXpath[i]}')]"
        elif type == self.WHOLE:
            _elementXpath = elementXpath[0].replace("//", f"{root}//")
        elif type == self.MATCH:
            _elementXpath = f"{root}//{elementType}[{what}='{elementXpath[0]}']"
            for i in range(1, len(elementXpath)):
                _elementXpath += f" | {root}//{elementType}[{what}='{elementXpath[i]}']"

        return self.smartClick(_elementXpath, indInList, travelUp, timeLimit, txtCond, checkClosed,
                     checkNewPage, checkNewTab, waitBeforeClicking, findFrom, waitBeforeFinding, expectingPopUp=False)

    def smartClick(self, elementXpath='', indInList=0, travelUp=0, timeLimit=10, txtCond = '', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0,
                   element=None , expectingPopUp=False, ctrl=False):

        if findFrom is None:
            findFrom = self.driver

        num_tabs_at_start = len(self.driver.window_handles)
        url_at_start = self.driver.current_url

        if element is not None:
            elementXpath = self.generate_full_xpath(element)


        spentWaiting = [0]
        while True:
            self.write("on line: " + str(inspect.currentframe().f_lineno))
            try:
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                #the "element" variable might be an exception object here
                element = self.clickAttempt(elementXpath, indInList, travelUp, txtCond,
                                            checkClosed,  checkNewPage,  checkNewTab,
                                            waitBeforeClicking, findFrom, waitBeforeFinding,
                                            url_at_start, num_tabs_at_start, expectingPopUp,
                                            ctrl)
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                break
            except Exception as e:
                if isinstance(e, IndexError):
                    raise
                self.write("on line: " + str(inspect.currentframe().f_lineno))
                if not self.delta_wait_4_click(elementXpath, spentWaiting, timeLimit):
                    self.write("on line: " + str(inspect.currentframe().f_lineno))
                    break
            self.write("on line: " + str(inspect.currentframe().f_lineno))
        self.write("on line: " + str(inspect.currentframe().f_lineno))
        return element

    def findClosestRelatives(self,  refWhat, refType, refXpath, targetWhat, targetType, targetXpath, limit=10, srchLvlLmt=float('inf')):
        reference = self.findAndClick(refWhat, refType,  refXpath, txtCond='@#%   Not Supposed To Match  ^&*()', timeLimit=limit)
        if reference is None:
            return []
        relatives = []
        prvWait = self.DELTA_WAIT  # elementXpath
        self.DELTA_WAIT = .01
        level = 0
        while True:
            relatives = self.findAndClick(targetWhat, targetType, targetXpath, indInList=self.ALL, timeLimit=limit,
                                          txtCond='@#%   Not Supposed To Match  ^&*()', findFrom=reference)
            if len(relatives) > 0:
                break
            try:
                reference = self.get_parent(reference)
            except:
                #We Will run into an exception if We try to get the parent of the top level element
                break

            level += 1
            if level > srchLvlLmt:
                break
        self.DELTA_WAIT = prvWait
        return relatives

    def findFillMoveOn(self, what, type, elementXpath, fillContent, indInList=0):
        element = self.findAndClick( what, type,elementXpath, indInList)
        self.fillMoveOn(element, fillContent)
        return element

    def findFillEnter(self, what, type,  elementXpath, fillContent, indInList=0):
        element = self.findAndClick( what, type,elementXpath, indInList)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(fillContent)
        element.send_keys(Keys.ENTER)
        return element


    def fillMoveOn(self, element, fillContent):
        try:
            element.send_keys(Keys.CONTROL, "a")
            for i in range(0, len(fillContent), 20):
                element.send_keys(fillContent[i:i+20])  #send 20 chars at a time
                element.send_keys(Keys.END) # make sure the cursor
            element.send_keys(Keys.TAB)
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()
            still = True
            while still:
                t.sleep(1)


    def fillDropDown(self, drpElement, content):
        self.smartClick(element=drpElement)
        drpElement.send_keys(content)
        drpElement.send_keys(Keys.ENTER)

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

    def reportAction(self, actionMsg, reportStack=True):
        print(f"\n{actionMsg}\n")
        if reportStack:
            stack = inspect.stack()
            listFuncCalls = [frame.function for frame in stack]
            listFuncCalls.pop(0)
            funcStack = ' | '.join(listFuncCalls)
            print(f"\tFunction Stack: {funcStack}\n")

    def getCurrentEnv(self):
        t.sleep(1)
        currentEnv = ""

        #  check if a dialog box is present
        #dialogBox = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@role="dialog" and @aria-modal="true"]',
        #                              txtCond="#$%^&*", timeLimit=.4)
        #  first handle URL
        url = self.driver.current_url

        # if so  get the text
        if False: #dialogBox is not None:
            mainText = dialogBox.text
            currentEnv = f"{url}|{mainText}"
        # if not, get the first <title>\
        else:
            while len(self.driver.title) <= 0:
                print(f"title is {self.driver.title} so sleeping for a second")
                t.sleep(1)
            cond = lambda : len(self.driver.title) > 0
            self.graduatedWait(cond, maxWait=5) #wait up to 2 secs for title to load
            titleText = self.driver.title
            currentEnv = f"{url}|{titleText}"

        return currentEnv

    def escape_regex_special_chars(self, s: str) -> str:
        # List of regex special characters that need to be escaped
        special_chars = ['\\', '.', '^', '$', '*', '+', '?', '{', '}', '[', ']', '|', '(', ')']

        #make the markers more complex
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



class IndeedHelper(SeleniumWrap):
    def __init__(self):
        self.MY_PATH = ''  # "Users\\name\\c
        self.home_url = ""
        self.home_url_pattern = ""
        self.chrome_profile = "user-data-dir="
        self.dataPath = "data\\"
        self.configPath = "config\\"
        self.promptsPath = 'prompts\\'
        self.load_startup_info()
        #self.home_url = "https://www.indeed.com/q-Customer-Service-Representative-$45,000-l-Remote-jobs.html?vjk=b7c0f1e66a8c20b8"
        #self.home_url_pattern = "https://www.indeed.com/q-Customer((.*))"
        #self.home_url = "https://www.indeed.com/jobs?q=&l=Remote&vjk=7917c10f99e95728"
        #self.home_url_pattern = "https://www.indeed.com/jobs?((.*))"
        super().__init__(self.home_url, self.home_url_pattern, self.chrome_profile)
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
        self.cityState = ''
        self.zip = ''
        self.country = 'United States'
        self.user_id = -1

        self.load_life_summary()
        self.load_edu()
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
        self.findAndClick( self.ARIA_LABEL, self.MATCH, "close icon", checkClosed=True)
    def newApp(self):
        #get next opening
        next(self.jobOpeningGenerator)
    def startApplication(self):
        # click on the Apply Now button if it is there
        return self.findAndClick(self.TXT, self.MATCH, 'Apply now', checkNewTab=True, timeLimit=3)

    def updateContactInfo(self):
        return self.handleAddInfoPage()
    def startResume(self):
        return self.chooseToBuildIndeedResume()

    def hitEditFromReviewPage(self):
        editButton = self.findClosestRelatives(self.TXT, self.MATCH, "Resume", self.TXT, self.MATCH, "Edit")[0]
        return self.smartClick(element=editButton)
    def addResume(self):
        return self.findAndClick(self.TXT, self.MATCH, 'Continue', travelUp=1, waitBeforeFinding=2)
    def backToDidContactInfo(self):
        pass
    def startContactInfo(self):
        return self.findAndClick(self.ID, self.CONTAINS, 'edit-contact-info', checkNewPage=True)
    def startSummary(self):
        # remove if already there
        delButs = self.findClosestRelatives( self.TXT, self.MATCH, 'Summary', self.ID, self.CONTAINS, 'delete',
                                            srchLvlLmt=2)
        if len(delButs) > 0:
            self.click_all(delButs)

        sumBut = self.findClosestRelatives(self.TXT, self.MATCH, 'Summary', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=sumBut, waitBeforeClicking=.7, checkNewPage=True)
    def startWorkExp(self):
        return self.do_work_exp()
    def startEdu(self):
        return self.do_edu()
    def startSkills(self):
        return self.do_skiils()
    def finishResume(self):
        return self.findAndClick(self.TXT, self.MATCH,  'Continue applying', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)
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
        #return self.fillEducationInfo()
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
        return self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7, checkNewPage=True)

    def continueFromPage(self):
        return self.findAndClick(self.TXT, self.MATCH, ["Continue", "Review your application"])
    def clickAddDocs(self):
        #  Find Supporting documents section and click on the add button
        try:
            addButton = self.findClosestRelatives(self.TXT, self.CONTAINS, 'Supporting documents',
                                                  self.WHOLE, self.WHOLE, "//a")[0]
        except:
            self.reportAction("Skipping the 'Add Docs' part because there doesn't seem to be a section for adding CL")
            return None
        return self.smartClick(element=addButton, checkNewPage=True)

    def prepDBCommit(self):
        companyInfo = f"{self.companyName}~+~{self.jobTitle}~+~{self.JobDescriptionText}"

        # full name
        fullName = f"{self.firstName} {self.lastName}"

        #prev job info
        resume = f"{fullName}~+~{self.headline}~+~{self.jobs}~+~{self.edus}~+~{self.skills}~+~{self.resumeSummary}"

        # save the application in database
        #self.saveAppInDB(companyInfo, resume, self.coverLetter)
        self.saveAppInDB(self.companyName, self.jobTitle, self.JobDescriptionText, fullName,
                         self.headline,  str(self.jobs), str(self.edus), str(self.skills),
                         self.resumeSummary, str(self.prev_questions), self.coverLetter)

    def saveUserInDB(self):
        emailCol = "IndeedEmail"
        passCol = "IndeedPass"
        checker_query = """SELECT * FROM users WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                          email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
        insert_query = f"""INSERT INTO users (FirstName, LastName, PhoneNumber, 
                                 email, address, cityState, country, zip, {emailCol}, {passCol})
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        values = [self.firstName, self.lastName, self.phone_num, self.email,
                        self.addr, self.cityState, self.country, self.zip]
        conn = sqlite3.connect('IndHelperDB.db')
        cursor = conn.cursor()

        # Create the table if it doesn't exist
        #cursor.execute('''CREATE TABLE IF NOT EXISTS users
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
            cursor.execute(insert_query,tuple(values))

            # Save (commit) the changes
            conn.commit()
            self.user_id = cursor.lastrowid
        else:
            self.user_id = existing_record[0]
            platformEmail = existing_record[-2]
            platformPass = existing_record[-1]
            for fname, field in [(emailCol, platformEmail), (passCol, platformPass)]:
                if not field:
                    values_ = tuple( [input(f"What is {self.firstName}'s {fname}")] + values)
                    update_query = f"""UPDATE users SET {fname} = ? WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                                  email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
                    cursor.execute(update_query, values_)
            print(f"User '{self.firstName}' already exists.")

        # Close the connection
        conn.commit()
        conn.close()

    #def saveAppInDB(self, companyInfo, resumeInfo, coverLetter):
    def saveAppInDB(self, companyName, jobTitle, JobDescriptionText, fullName, headline, jobHist,
                    eduHist, skills, resumeSummary, prevQsAs, coverLetter):
        #https://chat.openai.com/c/17e56ec1-3cb5-4b4b-8b64-5632efe21023

        current_date = datetime.datetime.now().isoformat(' ', 'seconds')

        # Connect to the resume_records database
        conn = sqlite3.connect('IndHelperDB.db')
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

        # Save (commit) the changes
        conn.commit()

        # Close the connection
        conn.close()
    def submitApp(self):
        self.prepDBCommit()
        # click the checkbox so they contact the person directly thru number too (maybe turn this off if you need to verify the leads)
        self.findAndClick(self.WHOLE, self.WHOLE, "//input[@type='checkbox']", travelUp=1, timeLimit=1)
        path_4_button_containing_span = "//button[span[contains(text(),'Submit')]]"
        return self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7, checkNewPage=True)
    def addDocs(self):
        return self.do_cover_letter()

    def quickWaitAndRefresh(self):
        t.sleep(10)
        self.driver.refresh()
        t.sleep(60)

    def backToStart(self):
        pattern = self.escape_regex_special_chars(self.home_url_pattern)
        self.select_tab_by_url_pattern(pattern)
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
        while True:
            #find the list of job openings
            openings = self.driver.find_elements(By.CSS_SELECTOR, '.css-5lfssm.eu4oa1w0')
            for opening in openings:
                #  check if it's a non-interactable opening
                try:
                    if len(opening.text) == 0 or "Easily apply" not in opening.text or "card" not in self.get_child(
                            opening).get_attribute("class"):
                        continue
                except Exception as e:
                    print("An error occurred:", e)
                    traceback.print_exc()
                    still = 456

                link = self.findAndClick(self.WHOLE, self.WHOLE, self.LINK, txtCond="asdf", findFrom=opening,
                                         timeLimit=1)

                try:
                    self.smartClick(element=link, ctrl=True)
                except:
                    self.smartClick(element=opening, ctrl=True)

                #  get job infos


                #rs = self.findClosestRelatives(self.CONTAINS, self.TXT, "s estimated salaries", self.CONTAINS, self.CLASS, 'CloseButton', limit=1)
                #if len(rs) == 1:
                #    self.click_all(rs)

                buttonElement = self.findAndClick(self.TXT, self.MATCH, 'Apply now',
                                                  timeLimit=5, txtCond="$%^& Dont click yet &*(")

                if buttonElement is None:
                    # means this is not a job that you can apply from Indeed site
                    self.backToStart()
                    continue

                #clear out prev Qs and As
                self.prev_questions.clear()

                # extract job info
                self.getPositionInfo()

                # check if this is one of the positions we want to avoid
                if self.jobContainsForbiddenCharacteristics():
                    print("Not proceeding with this job... it contains characteristics this user wants to avoid")
                    self.backToStart()
                    continue

                # load jobs and change job description based on the details of current job
                self.load_jobs()

                # generate CL
                self.generateCL()

                #generate skills
                self.generateSkills()

                # generate headline
                self.generateHeadline()

                #resume summary
                self.generateSummary()


                yield



            self.findAndClick(self.ARIA_LABEL,  self.MATCH, 'Next Page')

    def chooseToBuildIndeedResume(self):
        resButtonPath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[1]/div/div/div[2]/div[1]/div/div[2]/span[1]'
        editButtonPath = '//*[@id="edit-Ee5RAspBhdSgNHMSFzJyZg"]'

        #self.findAndClick(self.WHOLE, self.WHOLE, resButtonPath)
        self.findAndClick(self.TXT, self.CONTAINS, 'Indeed Resume', waitBeforeClicking=1)
        editButton = self.findAndClick( self.TXT, self.CONTAINS,'Edit resume', timeLimit=1)
        return editButton

    def handleAddInfoPage(self):
        #  if We find it, We're not gonna click it.  just Wanted to knoW if it Was there
        title = self.findAndClick(self.WHOLE, self.WHOLE, self.H1, timeLimit=2, txtCond='@#%^&*()')
        if title is not None and title.text == 'Add your contact information':
            fn = self.findClosestRelatives(self.TXT, self.MATCH, 'First name', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(fn, self.firstName)
            ln = self.findClosestRelatives(self.TXT, self.MATCH, 'Last name', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(ln, self.lastName)
            phone = self.findClosestRelatives(self.TXT, self.MATCH, 'Phone number', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(phone, self.phone_num)
            try:
                cS = self.findClosestRelatives(self.TXT, self.MATCH, 'City, State', self.WHOLE, self.WHOLE, '//input')[0]
                self.fillMoveOn(cS, self.cityState)
            except:
                pass
            return self.findAndClick(self.TXT, self.MATCH, "Continue", checkNewPage=True )

    def edit_contact_info(self):
        #self.findAndClick(self.CONTAINS, self.ID, 'edit-contact-info')
        fn_input = self.findClosestRelatives(self.TXT, self.MATCH, 'First name', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=fn_input)
        self.smartClick(element=fn_input)
        self.fillMoveOn(fn_input, self.firstName)

        ln_input = self.findClosestRelatives(self.TXT, self.MATCH, 'Last name', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=ln_input)
        self.fillMoveOn(ln_input, self.lastName)

        head_input = self.findClosestRelatives(self.TXT, self.MATCH,  'Headline', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=head_input)
        self.fillMoveOn(head_input, self.headline)  # need GPT

        phone_num_input = self.findClosestRelatives(self.TXT, self.MATCH, 'Phone', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=phone_num_input)
        self.fillMoveOn(phone_num_input, self.phone_num)  # need GPT

        showPhone = self.findClosestRelatives(self.ID, self.CONTAINS, 'showPhoneNumber', self.WHOLE, self.WHOLE, self.INPUT)[0]
        if not showPhone.is_selected():
            self.smartClick(element=showPhone)

        citystate_input = self.findClosestRelatives(self.TXT, self.CONTAINS,  'City, State', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=citystate_input)
        self.fillMoveOn(citystate_input, self.cityState)  # need GPT

        zip_input = self.findClosestRelatives(self.TXT, self.CONTAINS,  'Postal code', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=zip_input)
        self.fillMoveOn(zip_input, self.zip )  # need GPT

        result = self.findAndClick( self.TXT, self.MATCH, 'Save', travelUp=1, checkNewPage=True, timeLimit=.5)

        if result is None:
            result = self.findAndClick(self.ARIA_LABEL, self.MATCH, 'Back', checkNewPage=True, timeLimit=5)

        return result

    def do_summary(self):
        txtBoxPath = "//div[@role='textbox']"
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, self.resumeSummary) # need GPT
        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.5, checkNewPage=True)

    def do_education(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.MATCH,  'Education', self.ID, self.CONTAINS, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        addEduBut = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=addEduBut, waitBeforeClicking=.7)

        return self.fillEducationInfo()

    def handleEdu(self, edu : dict):
        eduLvl, fieldOS, schoolName, cityState, current, fromDate, toDate = tuple(edu.values())
        current = "y" in current.lower()

        # education level
        self.findFillMoveOn(self.ID, self.CONTAINS, 'educationLevel', eduLvl)

        # field of study
        self.findFillMoveOn(self.ID, self.CONTAINS, 'fieldOfStudy', fieldOS)

        # school name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'school', schoolName)

        # school location
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        # current position
        if current:
            self.findAndClick(self.ID, self.CONTAINS, 'isCurrent')

        #  drop downs
        drp_dwns = self.driver.find_elements('xpath', "//*[contains(@id, 'SelectFormField')]")
        frmMon, frmYr = tuple(drp_dwns[:2])
        frmMonCont, frmYrCont = tuple(fromDate.split(" "))
        self.fillDropDown(frmMon, frmMonCont)
        self.fillDropDown(frmYr, frmYrCont)

        if not current:
            toMon, toYr = tuple(drp_dwns[2:])
            toMonCont, toYrCont = tuple(toDate.split(" "))
            self.fillDropDown(toMon, toMonCont)
            self.fillDropDown(toYr, toYrCont)

        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)

    def do_skiils(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.MATCH, 'Skills', self.ID, self.CONTAINS,  'delete', srchLvlLmt=2)
        self.click_all(deletes, delayBeforeEach=.1, timeLimitForEach=1)

        for skill in self.skills:
            if "and" == skill[:3]:
                skill = skill[4:]
            if " and" == skill[:4]:
                skill = skill[5:]
            try:
                addSkillBut = self.findClosestRelatives(self.TXT, self.MATCH,  'Skills', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            except:
                traceback.print_exc()
                h = 3
            self.smartClick(element=addSkillBut, waitBeforeClicking=.7, checkNewPage=True)
            self.findFillMoveOn(self.ID, self.CONTAINS, 'skillName', skill)
            possExp = self.finalizeResumeSection()
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp

    def fillSkills(self):
        # generate a list of skills using chat GPT here
        for skill in self.skills:
            self.findFillEnter( self.ID, self.CONTAINS,'new-skill-form', skill)

    def do_work_exp(self):
        #delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.CONTAINS, 'Work experience', self.ID, self.CONTAINS, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        for job in self.jobs:
            try:
                addWorkBut = self.findClosestRelatives(self.TXT, self.MATCH ,  'Work experience', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            except:
                traceback.print_exc()
                h = 3
            self.smartClick(element=addWorkBut, waitBeforeClicking=.7, checkNewPage=True)
            possExp = self.handleJob(job)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp
    def do_edu(self):
        # delete all prior
        deletes = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.ID, self.CONTAINS,
                                            'delete', srchLvlLmt=2)
        self.click_all(deletes)

        for edu in self.edus:
            addEduBut = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.smartClick(element=addEduBut, waitBeforeClicking=.7, checkNewPage=True)
            possExp = self.handleEdu(edu)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp


    def process_job_file(self, filename):
        jobFile = open(filename, "r")
        infoDict = {}
        for subject in ['title', 'comp', 'compType', 'cityState', 'current', 'fromDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(jobFile), self.nextNonBlankLine(jobFile).strip()


        #read the rest of the lines, that'll be the description
        _, rawDesc = self.nextNonBlankLine(jobFile), jobFile.read().strip()
        '''mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()'''

        mygpt = myGPT2("job_desc_prompts2.txt", self.jobTitle, self.JobDescriptionText, infoDict['title'],
                      infoDict['compType'],  rawDesc, infoDict['title'], infoDict['compType'])

        doAgain = True
        while doAgain:
            jobDesc = mygpt.sendAll().replace("Here are the 3 points from TheBig3:", "").strip()
            doAgain = mygpt.need_redo
        infoDict['desc'] = jobDesc

        return infoDict

    def process_edu_file(self, filename):
        eduFile = open(filename, "r")
        infoDict = {}
        for subject in ['educationLevel', 'fieldOfStudy', 'school', 'cityState', 'current', 'frmDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(eduFile), self.nextNonBlankLine(eduFile).strip()

        return infoDict

    def load_jobs(self):
        self.jobs.clear()
        files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)
        jobFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]

        for jobFile in jobFiles:
            self.jobs.append(self.process_job_file(jobFile))

    def load_edu(self):
        self.edus.clear()
        files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)
        eduFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Edu\d+\.txt$', f)]

        for eduFile in eduFiles:
            self.edus.append(self.process_edu_file(eduFile))

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

    def handleJob(self, job : dict ):
        title, comp, cityState, current, fromDate, toDate, desc = tuple(job.values())
        current = "y" in current.lower()

        # Job Title
        self.findFillMoveOn(self.ID, self.CONTAINS, 'jobTitle', title)

        # company name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'company', comp)

        # city state
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        # current position
        if current:
            self.findAndClick( self.ID, self.CONTAINS,'isCurrent')

        #  drop downs
        drp_dwns = self.driver.find_elements('xpath', "//*[contains(@id, 'SelectFormField')]")
        frmMon, frmYr = tuple(drp_dwns[:2])
        frmMonCont, frmYrCont = tuple(fromDate.split(" "))
        self.fillDropDown(frmMon, frmMonCont)
        self.fillDropDown(frmYr, frmYrCont)

        if not current:
            toMon, toYr = tuple(drp_dwns[2:])
            toMonCont, toYrCont = tuple(toDate.split(" "))
            self.fillDropDown(toMon, toMonCont)
            self.fillDropDown(toYr, toYrCont)

        # description
        txtBoxPath = "//div[@role='textbox']"
        descEle = self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)  # need GPT

        while any([descPoint[2:] not in descEle.text for descPoint in desc.split("\n")]):
            self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)

        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)


    def checkIfMoreQuestionsAppeared(self, tup_ptr):
        allPageQuestions, origQuestSet, questn = tup_ptr
        nextQuestInd = allPageQuestions.index(questn) + 1
        QsLeft = allPageQuestions[nextQuestInd:]
        del allPageQuestions[nextQuestInd:]
        latestAllQs = set(self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                            indInList=self.ALL, txtCond="#$%^&*(KJH"))
        newQs = latestAllQs - origQuestSet
        origQuestSet.clear()
        origQuestSet.update(latestAllQs)
        allPageQuestions.extend(newQs)
        allPageQuestions.extend(QsLeft)

    def analyzeAndAnsQuestions(self):
        allPageQuestions = self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                             indInList=self.ALL, txtCond="#$%^&*(KJH")

        origQuestSet = set(allPageQuestions)
        if len(allPageQuestions) > 0:
            url1 = self.driver.current_url
            # hit continue. Since no answers are chosen, this
            # wont be allowed and all the question error txt will appear
            self.findAndClick(self.TXT, self.MATCH,  'Continue', travelUp=1, waitBeforeClicking=.2)

            # if the url changed (meaning that our old responses were used)then just finish/return
            t.sleep(2)
            url2 = self.driver.current_url
            if url1 != url2:
                return  # nothing to do...questions already answered


            for questn in allPageQuestions:
                try:
                    ret = self.process_question(questn)
                    if isinstance(ret, BadPost):
                        return ret
                    #after answering quesiton, see if any more pop up
                    self.checkIfMoreQuestionsAppeared( (allPageQuestions, origQuestSet, questn) )

                except:
                    traceback.print_exc()
                    h = 3

            return self.keepGoing()

    def checkIfQuestionAlreadyAnswered(self, questn, type, answer_choices):
        if type == self.FreeResponse or type == self.FreeResponseLong:
            prevTxt = answer_choices['inputBox'].get_attribute("value")
            return len(prevTxt) > 0
        elif type == self.MultChoice:
            # check if already answered
            checked = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@checked]', txtCond="asdf", findFrom=questn,
                                        timeLimit=1)
            return checked is not None
        elif type == self.DropDown:
            return answer_choices['dropDown'].get_attribute("value") != ""
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

    def ensureQualityOfFreeRespAns(self, gptObj, questn, helpTxt, ans):
        qxpath = self.generate_full_xpath(questn)
        updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
        _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        while errorTxt is not None:
            ans = gptObj.sendFromFile("free_resp_choice_wrong_prompts.txt", helpTxt)
            self.fillMoveOn(answer_choices['inputBox'], ans)
            qxpath = self.generate_full_xpath(questn)
            updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
            _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        return ans


    def getTopChoiceScore(self, ans, answer_choices):
        choices_n_scores = [(ans_choice, self.jaccard_similarity(ans_choice, ans)) for ans_choice in
                            answer_choices.keys()]
        choices_n_scores.sort(key=lambda x: x[1], reverse=True)
        thresh = self.jaccard_similarity(ans + "~`*", ans)
        topChoice, topScore = choices_n_scores[0]
        return topChoice, topScore, thresh
    def ensureQualityOfMultChoiceAns(self, gptObj, answer_choices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt").split("The answer is:")[1]
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)
        inputElement = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="adsfadsfads",
                                         findFrom=answer_choices[topChoice])
        while not inputElement.is_selected():
            self.smartClick(element=answer_choices[topChoice])
        return topChoice

    def ensureQualityOfSelectApplicableAns(self, gptObj, answer_choices, ans):
        answers = ans
        topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]
        while any(topScore < thresh for topChoice, topScore, thresh in topChoiceScoreThresh):
            answer = gptObj.sendFromFile("select_applicable_wrong_prompts.txt")
            answers = [thing.strip() for thing in answer.split("\n") if len(thing.strip()) > 0 ]
            topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]

        final_answers = []
        for topChoice, topScore, thresh in topChoiceScoreThresh:
            inputElement = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="adsfadsfads",
                                             findFrom=answer_choices[topChoice])
            while not inputElement.is_selected():
                self.smartClick(element=answer_choices[topChoice])
            final_answers.append(topChoice)
        return str(final_answers)


    def ensureQualityOfDropDownAns(self, gptObj, answer_choices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices['answers'])
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt")
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices['answers'])
        print(f"b4  *{answer_choices['dropDown'].get_attribute('value')}*")
        while answer_choices['dropDown'].get_attribute("value") == "":
            print(f"b4 send eys  *{answer_choices['dropDown'].get_attribute('value')}*")
            answer_choices['dropDown'].send_keys(topChoice)
            print(f"after send eys  *{answer_choices['dropDown'].get_attribute('value')}*")
        return topChoice

    def relevantSubStr(self, substr, fullStr):
        maxLen = len(substr)*1.5
        # Escape any special characters in substr
        escaped_substr = re.escape(substr.lower())
        # Construct the regular expression pattern
        pattern = rf'^(?!.{{{maxLen},}})(.*[^a-zA-Z])?{escaped_substr}([^a-zA-Z].*)?$'
        # Check if the string matches the pattern
        return bool(re.match(pattern, fullStr))

    def checkIfAPreMadeAnswerFits(self, questn_txt, type, answer_choices):
        detailKeysOrdrd = list(self.details.keys())
        detailKeysOrdrd.sort(key=lambda x:len(x), reverse=True)
        ourAns = None
        for detKey in detailKeysOrdrd:
            if self.relevantSubStr(detKey, questn_txt.lower()):
                ourAns = self.details[detKey]
                break
        if ourAns is not None:
            if type == self.DropDown:
                answer_choices['dropDown'].send_keys(ourAns)
            elif type == self.FreeResponse:
                self.fillMoveOn(answer_choices['inputBox'], ourAns)
            else:
                return False
            return True
        else:
            return False
    def process_question(self, questn):  #//div[contains(@class, 'Questions-item')]
        #Do we even have to do this question?
        txt = questn.text
        if '(optional)' in txt:
            return

        questn_txt, answer_choices, errorTxt, type = self.extractQuestionInfo(questn)

        if isinstance(type, BadPost):
            return type

        if self.checkIfQuestionAlreadyAnswered(questn, type, answer_choices):
            return

        if self.checkIfAPreMadeAnswerFits(questn_txt, type, answer_choices):
            return

        helpTxt = "Answer as concisely and in as natural a way as possible"
        if errorTxt is not None:
            helpTxt = errorTxt.text

        self.txt = questn_txt


        #  get ans back from chat GPT
        ans = None
        final_answer = None
        if type == self.FreeResponse or type == self.FreeResponseLong:
            # get chat GPT help with free response question
            mygpt = myGPT2("free_response_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                          self.lifeSummary, questn_txt, helpTxt, self.zip, self.phone_num, self.email, version=1)
            ans = mygpt.sendAll()
            self.fillMoveOn(answer_choices['inputBox'], ans)

            final_answer = self.ensureQualityOfFreeRespAns(mygpt, questn, helpTxt, ans)

        elif type == self.DateFill:
            # get chat GPT help with free response question
            mygpt = myGPT2("date_fill_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                        questn_txt, self.today_mmddyyy(), helpTxt, version=1)
            ans = mygpt.sendAll()
            self.fillMoveOn(answer_choices['inputBox'], ans)

            final_answer = self.ensureQualityOfDateRespAns(mygpt, questn, helpTxt, ans)


        elif type == self.MultChoice:
            #get chat GPT help
            mygpt = myGPT2("mult_choice_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1)
            ans = mygpt.sendAll().split("The answer is:")[1]

            final_answer = self.ensureQualityOfMultChoiceAns(mygpt, answer_choices, ans)

        elif type == self.SelectApplicable:
            #get chat GPT help
            mygpt = myGPT2("select_applicable_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1)
            ans = mygpt.sendAll()
            ans_list = [thing.strip() for thing in ans.split("\n") if len(thing.strip()) > 0 ]

            final_answer = self.ensureQualityOfSelectApplicableAns(mygpt, answer_choices, ans_list)


        elif type == self.DropDown:
            # get chat GPT help
            mygpt = myGPT2("drop_down_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, str(self.details), self.lifeSummary,  "\n".join(list(answer_choices['answers'].keys())),
                           helpTxt, version=1)
            ans = mygpt.sendAll()

            #  break here because need to verify that dropdwn is actually the corrct element to send answer to
            final_answer = self.ensureQualityOfDropDownAns(mygpt, answer_choices, ans)

        self.prev_questions.append({"Question":questn_txt, "Answer":final_answer})


    def extractQuestionInfo(self, questn):
        ans_dict = {
            # format =  "Yes": <obj>
            # format =  "No": <obj>
        }
        intermediate_ans_list = []
        questionText = ""
        # determine type  //*[@aria-label="Day and time option"]
        type = self.determine_question_type(questn)

        if isinstance(type, BadPost):
            return None, None, None, type

        #get error text
        errorTxt = self.findAndClick(self.ID,  self.CONTAINS, 'errorText', txtCond="$%^&*()", findFrom=questn, timeLimit=2)
        if errorTxt is None:
            errorTxt = self.findAndClick(self.WHOLE, self.WHOLE, "//span[@role='alert']", txtCond="$%^&*()", findFrom=questn, timeLimit=2)
        elif self.num_children(errorTxt) == 0:
            errorTxt = None

        #get answer choices & question text
        try:
            if type == self.FreeResponse or type == self.FreeResponseLong or type == self.DateFill:
                ans_dict['inputBox'] = self.findAndClick(self.WHOLE, self.WHOLE, self.xpath_or(self.INPUT, self.TXTAREA) , findFrom=questn)
                if ans_dict['inputBox'] is None:
                    type = self.Bad
                txtRoot = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn)
                questionText = {self.FreeResponse: txtRoot.text,
                                self.DateFill: txtRoot.text,
                                self.FreeResponseLong: txtRoot.text.split("\n")[-1].replace("\"", "")}[type]

            elif type == self.MultChoice:
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
                ans_dict = { element.text : element for element in intermediate_ans_list}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, '//legend', findFrom=questn).text
            elif type == self.DropDown:
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.OPTION, findFrom=questn, indInList=self.ALL)
                ans_dict = {}
                ans_dict['answers'] = { element.text : element for element in intermediate_ans_list if len(element.text) > 0 }
                ans_dict['dropDown'] = self.findAndClick(self.WHOLE, self.WHOLE, '//select', findFrom=questn)
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn).text
            elif type == self.SelectApplicable:
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
                intermediate_ans_list.pop(0)
                ans_dict = {element.text: element for element in intermediate_ans_list}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="zdsffd").text
            elif type == self.Bad:
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn).text
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()
            still = True
            while still:
                t.sleep(1)

        if "(optional)" in questionText:
            type = self.Bad

        return questionText, ans_dict, errorTxt, type

    def redirectAndSkip(self, message):
        self.driver.get("https://www.google.com")
        try:
            alert = self.driver.switch_to.alert
            alert.accept()
        except:
            pass
        return BadPost(message)

    def determine_question_type(self, questn):
        try:
            qChild = self.get_child(questn, 1, 1)
        except:
            return self.Bad

        num = self.num_children(qChild)
        listOfBad = self.findAndClick( '@aria-label', self.MATCH, 'Day and time option', findFrom=questn, indInList=self.ALL)
        if len(listOfBad) > 0 or self.num_children(self.get_child_complex(questn, "1/2")) == 0:
            # then it's a question we don't want
            return self.Bad
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//fieldset", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            #  also contains input, find out what kind of input (radio or checkbox)
            inputEle = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="asdf", findFrom=questn, timeLimit=.1)
            typeOfInput = inputEle.get_attribute("type")
            return {"radio": self.MultChoice, "checkbox": self.SelectApplicable}[typeOfInput]
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//div[@role='group']", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            return self.redirectAndSkip("This was the group... analzye and see..")
        elif self.findAndClick(self.ID, self.CONTAINS, "FileUpload", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            #redirect to google because that's the environment that tells us we need to skip this post
            return self.redirectAndSkip("They wanted us to upload a file... fuck that.. not dealing with it")
        elif self.findAndClick(self.WHOLE, self.WHOLE, self.TXTAREA, findFrom=questn, timeLimit=.1, txtCond="^&*") is not None:
            return self.FreeResponseLong

        elif self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            if self.findAndClick(self.WHOLE, self.WHOLE, self.BUTTON, findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
                return self.DateFill
            else:
                return self.FreeResponse

        elif self.findAndClick(self.WHOLE, self.WHOLE, self.SELECT, findFrom=questn, timeLimit=.1, txtCond="%^&") is not None:
            return self.DropDown
        else:
            return self.Bad



    def do_cover_letter(self):

        selection = self.findAndClick(self.ID, self.CONTAINS,  'write-cover-letter-selection-card')

        self.findFillMoveOn(self.WHOLE, self.WHOLE, self.TXTAREA, self.coverLetter)

        return self.findAndClick(self.TXT, self.MATCH, 'Update', travelUp=1, checkNewPage=True)


    def addAnother(self):
        self.findAndClick(self.TXT, self.CONTAINS,  'Add another', travelUp=1)


    def finalizeResumeSection(self):
        self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)

    def nextResumeSection(self):
        self.findAndClick( self.TXT, self.MATCH, 'Save and continue', travelUp=1)



    def load_startup_info(self):
        # purpose of '_' is to skip the explanation of the next line/section
        # nextOccrance(self,file_handler, substr, delim="\t", after=""):
        try:
            f = open(self.configPath + "StartUpInfo.txt", 'r')
            _, my_path_id         =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            self.MY_PATH          =  "Users\\" + my_path_id + "\\"
            self.home_url         =  self.nextOccurance(f, my_path_id)
            self.home_url_pattern =  self.nextOccurance(f, my_path_id)
            self.chrome_profile  +=  self.nextOccurance(f, my_path_id)
        except:
            return


    def load_life_summary(self):
        # purpose of '_' is to skip the explanation of the next line/section
        try:
            f = open(self.MY_PATH + self.dataPath + "LifeSummary.txt", 'r')
            _, self.firstName = self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.lastName  =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.phone_num =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.email     =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.addr      = self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.cityState =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.zip       =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)

            #skip explanation for summary
            self.nextNonBlankLine(f)

            self.lifeSummary  =  self.readRestNonBlank(f)  # read the rest
            self.setDetails()
            self.saveUserInDB()
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()

    def setDetails(self):
        c, s = tuple(self.cityState.split(","))
        self.details = {"name": f"{self.firstName} {self.lastName}",
                        "first name": self.firstName,
                        "last name": self.lastName,
                        "number":self.phone_num, "phone":self.phone_num,
                        "phone number":self.phone_num.replace("(", "").replace(")", "").replace(" ", "").replace("-", ""),
                        "email": self.email,
                        "address":self.addr,
                        "city":c, "state":s.strip(), "country":"United States",
                        "zip":self.zip}



    def jobContainsForbiddenCharacteristics(self):
        # get the avoidance qualities
        avoidFile = open(self.MY_PATH + self.dataPath + "AvoidTheseJobCharacteristics.txt", 'r')
        avoidLines = avoidFile.read().strip()
        if len(avoidLines) > 0:
            mygpt = myGPT2("avoid_job_characteristics_prompts.txt", self.JobDescriptionText, avoidLines, version=1)
            return 'yes' in mygpt.sendAll().lower()
        else:
            return False

    def getPositionInfo(self):
        x = "//*[@data-testid='inlineHeader-companyName']"
        compNameEle = self.findAndClick(self.WHOLE, self.WHOLE, x, txtCond="dsfdsd324", timeLimit=1)
        self.companyName = compNameEle.text


        spanElement = self.findAndClick(self.WHOLE, self.WHOLE, "//span[contains(text(), '- job post')]", txtCond="33343vscads", timeLimit=2)
        if spanElement is not None:
            titleElement = self.get_parent(spanElement )
        else:
            titleElement = self.findAndClick(self.WHOLE, self.WHOLE, self.H1, txtCond="adfddfsa", timeLimit=1)
        self.jobTitle = titleElement.text.split("\n")[0]

        jobDescElement = self.findAndClick(self.ID, self.MATCH, 'jobDescriptionText', txtCond='adsfdasf134')
        self.JobDescriptionText = jobDescElement.text

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
                      self.email, self.cityState, self.today())

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
        skillsStrList2 = skillsStrList2.replace("Here is the revised list:", "").strip().strip(".")
        self.skills = skillsStrList2.split(";;")
        self.tries.append({"1":firstTry, "2":secTry})

    def run(self):
        self.start_up()

        input("Press enter when you have signed in.")

        #for each page, process the job openings
        self.process_job_openings()


class StateMachine:
    def __init__(self, helper : SeleniumWrap ):
        self.helper = helper
        self.validate_files("States.txt", "ExpectedEnvironments.txt", "StateTransitions.txt")
        self.states = self.load_states("States.txt")
        self.expected_environments = self.load_environments("ExpectedEnvironments.txt")
        self.transitions = self.load_transitions("StateTransitions.txt")
        self.current_state = self.states[0]


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
            print(f"Environments missing in {state_transitions_file}:{sep}{sep.join(missing_environments_in_transitions)}")
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
            return [line.strip() for line in f.readlines()  if line[:2] != "//" and len(line.strip()) > 0]

    def load_environments(self, filename):
        with open(self.helper.configPath + filename, "r") as f:
            return [self.helper.escape_regex_special_chars(line.strip()) for line in f.readlines() if line[:2] != "//" and len(line.strip()) > 0 ]

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
        #equivalent:
        #return next( (pattern for pattern in sorted(self.expected_environments, key=len, reverse=True)
        #            if re.match(pattern.lower(), environment.lower()) ) , None )
        return None

    def envNextTrans(self, environment):
        #here next is taking in 2 args: 1) a generator and 2) a defualt value for gen if empty
        return next( (pattern for pattern in sorted(self.transitions.keys(), key=len, reverse=True)
                    if re.match(pattern.lower(), environment.lower()) ) , None )


    def transition(self, environment):
        t.sleep(1)
        envPattern = self.envIsValid(environment)
        if not envPattern:
            print(f"Unexpected environment: {environment}")
            self.waitForever()
            return

        next_state = None
        #checking that the transition file as made properly
        if self.envNextTrans(environment) is not None:
            if self.current_state in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern][self.current_state]
            elif "default" in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern]["default"]
            else:
                print(f"No transition for state {self.current_state} and env {environment}")

            if "default" == next_state.strip():
                next_state = self.current_state

            self.helper.reportAction(f"Calling function: {funcName}() in environment: {environment}", False)
            funcResult  = self.executeFunc(funcName)
            # need to check that we accomplished what we wanted to accomplish with this function
            if not isinstance(funcResult, ElementClickInterceptedException):
                self.helper.reportAction(f"Transitioning  STATE from {self.current_state} to {next_state}", False)
                self.current_state = next_state
            else:
                self.helper.reportAction(f"Not Transitioning  STATE from {self.current_state} to {next_state} because function failed somewhere.  Remaining in state to try again")

        else:
            print(f"No transition defined for environment: {environment}")
            self.waitForever()

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        return method_to_call()

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


if __name__ == "__main__":
    #ih = IndeedHelper()
    #ih.run()
    sm = StateMachine(IndeedHelper())
    sm.run()


#ih = IndeedHelper()
#ih.run()

#https://www.indeed.com/jobs?q=&l=Remote&radius=35&start=10&pp=gQAPAAABiqZMUOEAAAACEQs_OgApAQAGAbWQDBy232HQyRWcqeGmhCw1EBtXt2H_3ngANxzAD_7ga50Vm1QAAA&vjk=5bb2ac5d6d7a7740