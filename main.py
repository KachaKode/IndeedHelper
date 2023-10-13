# This is a sample Python script.

# GPT HELP:  https://chat.openai.com/c/aec09a74-238d-4f97-b49a-b6ca98e1d810

#Note  need to set up dummy chrome profile if you want browser to remember things

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, ElementClickInterceptedException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import datetime
import traceback
import sys
import os, re
import inspect
import time as t
#import openai
from myGPT import myGPT
#from selenium import webdriver
#import webdriver_manager
#from webdriver_manager.chrome import ChromeDriverManager


class SeleniumWrap:

    def __init__(self, home_url):
        self.chrome_profile = "user-data-dir=C:\\Users\\PJuJu\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 3"
        self.CONTAINS = "contains"
        self.MATCH = "matched"
        self.WHOLE = "whole"
        self.TXT = "text()"
        self.ID = "@id"
        self.CLASS = "@class"
        self.BUTTON = "//button"
        self.LABEL = "//label"
        self.INPUT = "//input"
        self.LIST = "//ul"
        self.LIST_ELEMENT = "//li"
        self.TXTAREA = '//textarea'
        self.ARIA_LABEL = '@aria-label'
        self.DELTA_WAIT = .2
        self.ALL = float('inf')
        self.home_url = home_url

    def nextNonBlankLine(self, file_handler):
        # This function will yield non-blank lines from the file
        line = ''
        while not line or line.strip()[:2] == "//":
            line = file_handler.readline().strip()
        return line

    def process_list_element(self, listElement):
        listMemberElements = self.findAndClick(self.WHOLE, self.WHOLE, self.LIST_ELEMENT,
                                               indInList=self.ALL, findFrom=listElement)
        listMemberText = []
        for memElement in listMemberElements:
            listMemberText.append(memElement.text)
        return listMemberText

    def getListByTitle(self, titleText):
        listElements = self.findClosestRelatives(self.CONTAINS, self.TXT, titleText, self.WHOLE, self.WHOLE, self.LIST)
        return listElements[0]

    def clickButtonByText(self, buttonText, checkNewPage=False, checkNewTab=False, checkClosed=False, waitBeforeClicking=0):
        button = self.findClosestRelatives(self.CONTAINS, self.TXT, buttonText,
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
            return

        # Close all other tabs
        for tab in all_tabs:
            if tab != matching_tab:
                self.driver.switch_to.window(tab)
                self.driver.close()

        # Switch to the matching tab
        self.driver.switch_to.window(matching_tab)

    def click_all(self, list_of_elements, delayBeforeEach=0, delayBeforeFirst=0):
        t.sleep(delayBeforeFirst)
        for element in list_of_elements:
            self.smartClick(element= element, waitBeforeClicking=delayBeforeEach)

    def clickChecker(self, element, checked, cond):
        #check if condition is already met
        if cond():
            self.reportAction("post-Click condition already met before even clicking")
        else:
            try:  # if a new page is expected, then element might become unclickable
                possibleExp = self.delayedClick(element)
                if isinstance(possibleExp, ElementClickInterceptedException):
                    return possibleExp
            except:
                # it's okay if an exception happens here.  Since we previously found the
                # element, we know it's only unclickable here because the page changed
                pass
            t.sleep(self.DELTA_WAIT)
        checked[0] = cond()
        return checked[0]

    def clickAttempt(self, elementXpath, indInList , travelUp , txtCond , checkClosed,  checkNewPage,
                     checkNewTab , waitBeforeClicking , findFrom , waitBeforeFinding, url_at_start, num_tabs_at_start  ):

        t.sleep(waitBeforeFinding)

        # if looking for a list of all matches then don't need to click
        if indInList == self.ALL:
            matches = findFrom.find_elements('xpath', elementXpath)
            self.reportAction(f"returning {len(matches)} matches for {elementXpath}!")
            return matches


        elementList = findFrom.find_elements('xpath', elementXpath)
        element = elementList[indInList]
        numElementsOriginally = len(elementList)

        #the elemenet being disabled is the same as it not being there
        if element.get_attribute("disabled") is not None:
            return None

        # travel upwards if specified...
        for i in range(travelUp, 0, -1):
            element = self.get_parent(element)
        possibleExp = None

        if txtCond == '' or txtCond == element.text:
            checked = [False]
            while not checked[0]:
                if waitBeforeClicking > 0:
                    possibleExp = self.delayedClick(element, waitBeforeClicking, checked)
                if checkNewPage:
                    #cond = lambda: url_at_start != self.driver.current_url
                    def condFunc():
                        cur_url = self.driver.current_url
                        self.reportAction(f"checking:\n\tURL before:{url_at_start}\n\tURL after:{cur_url}")
                        return  url_at_start != cur_url
                    possibleExp = self.clickChecker(element, checked, condFunc)
                elif checkNewTab:
                    #cond = lambda: num_tabs_at_start != len(self.driver.window_handles)
                    def condFunc():
                        self.reportAction(f"checking:\n\ttabs before:{num_tabs_at_start}\n\ttabs after:{len(self.driver.window_handles)}")
                        return  num_tabs_at_start != len(self.driver.window_handles)

                    possibleExp = self.clickChecker(element, checked, condFunc)
                    if possibleExp and not isinstance(possibleExp, Exception) :
                        # go to ne tab
                        self.goToNewTab()
                elif checkClosed:
                    def condFunc():
                        updatedElementList = findFrom.find_elements('xpath', elementXpath)
                        self.reportAction(
                            f"checking:\n\t# elements before:{numElementsOriginally}\n\t# elements after:{len(updatedElementList)}")
                        return  len(updatedElementList) < numElementsOriginally

                    possibleExp = self.clickChecker(element, checked, condFunc)
                else:
                    possibleExp = self.delayedClick(element)
                    checked[0] = True

                #handle possible exception
                if isinstance(possibleExp, ElementClickInterceptedException):
                    return possibleExp

            self.reportAction(f"clicked {elementXpath} successfully!")
        else:
            self.reportAction(f"found element {elementXpath} but did not click because text did not match: {txtCond}")
        return element

    def delayedClick(self, element, waitBeforeClicking=.05, checked=None):
        try:
            #attempt to scroll element to center screen
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            t.sleep(max(waitBeforeClicking, .05))
            if checked is not None:
               checked[0] = True
            element.click()
        except Exception as e:
            if isinstance(e, StaleElementReferenceException):
                # If the exception is of type StaleElementReferenceException, re-raise it so it
                # propagates up the call stack and is ignored by clickChecker().  But we wanna catch
                # all other exceptions.
                raise
            if isinstance(e, ElementClickInterceptedException):
                # If the exception is of type ElementClickInterceptedException, RETURN (not re-raise) the
                # exception so it propagates up and we don't change the state
                self.reportAction("Ran into ElementClickInterceptedException trying to click last found element")
                checked[0] = e
                return e
            print("An error occurred:", e)
            traceback.print_exc()
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

    def findAndClick(self, type, what, elementXpath, indInList=0, travelUp=0, timeLimit=10, txtCond = '', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0 ):
        root = ""
        if findFrom is None:
            findFrom = self.driver
        else:
            root = "."

        if type == self.CONTAINS:
            elementXpath = f"{root}//*[contains({what}, '{elementXpath}')]"
        elif type == self.WHOLE:
            elementXpath = elementXpath.replace("//", f"{root}//")
        elif type == self.MATCH:
            elementXpath = f"{root}//*[{what}='{elementXpath}']"

        return self.smartClick(elementXpath, indInList, travelUp, timeLimit, txtCond, checkClosed,
                     checkNewPage, checkNewTab, waitBeforeClicking, findFrom, waitBeforeFinding)

    def smartClick(self, elementXpath='', indInList=0, travelUp=0, timeLimit=10, txtCond = '', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0,
                   element=None ):

        if findFrom is None:
            findFrom = self.driver

        num_tabs_at_start = len(self.driver.window_handles)
        url_at_start = self.driver.current_url

        if element is not None:
            elementXpath = self.generate_full_xpath(element)


        spentWaiting = [0]
        while True:
            try:
                #the "element" variable might be an exception object here
                element = self.clickAttempt(elementXpath, indInList, travelUp, txtCond,
                                            checkClosed,  checkNewPage,  checkNewTab,
                                            waitBeforeClicking, findFrom, waitBeforeFinding,
                                            url_at_start, num_tabs_at_start)
                break
            except:
                if not self.delta_wait_4_click(elementXpath, spentWaiting, timeLimit):
                    break
        return element

    def findClosestRelatives(self, refType, refWhat, refXpath, targetType, targetWhat, targetXpath, limit=10, srchLvlLmt=float('inf')):
        reference = self.findAndClick(refType, refWhat, refXpath, txtCond='@#%   Not Supposed To Match  ^&*()', timeLimit=limit)
        if reference is None:
            return []
        relatives = []
        prvWait = self.DELTA_WAIT  # elementXpath
        self.DELTA_WAIT = .01
        level = 0
        while True:
            relatives = self.findAndClick(targetType, targetWhat, targetXpath, indInList=self.ALL, timeLimit=limit,
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

    def findFillMoveOn(self, type, what, elementXpath, fillContent, indInList=0):
        element = self.findAndClick( type, what,elementXpath, indInList)
        self.fillMoveOn(element, fillContent)

    def findFillEnter(self, type, what, elementXpath, fillContent, indInList=0):
        element = self.findAndClick(type, what, elementXpath, indInList)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(fillContent)
        element.send_keys(Keys.ENTER)


    def fillMoveOn(self, element, fillContent):
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(fillContent)
        element.send_keys(Keys.TAB)


    def fillDropDown(self, drpElement, content):
        self.smartClick(element=drpElement)
        drpElement.send_keys(content)
        drpElement.send_keys(Keys.ENTER)

    def get_parent(self, element, level=1):
        for i in range(level):
            element = element.find_element('xpath', '..')
        return element

    def get_child(self, element, level=1, indInLevel=1):
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

        return element.find_elements('xpath', finalPath)[0]

    def num_children(self, element):
        return len(element.find_elements('xpath', './*'))

    def indexAmongSiblings(self, element):
        index = len(element.find_elements('xpath', './preceding-sibling::*'))
        return index + 1

    def getNextSibling(self, element):
        indOfSibling = self.indexAmongSiblings(element) + 1
        parent = self.get_parent(element)
        return self.get_child(parent, indInLevel=indOfSibling)

    def generate_full_xpath(self, element):
        # Base case: if the element is the root html element
        if element.tag_name == "html":
            return "/html"

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
        currentEnv = ""

        #  check if a dialog box is present
        dialogBox = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@role="dialog" and @aria-modal="true"]',
                                      txtCond="#$%^&*", timeLimit=.4)
        #  first handle URL
        url = self.driver.current_url

        # if so  get the text
        if dialogBox is not None:
            mainText = dialogBox.text
            currentEnv = f"{url}|{mainText}"
        # if not, get the first <title>\
        else:
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
        super().__init__("https://www.indeed.com/jobs?q=&l=Remote&vjk=7917c10f99e95728")
        self.dataPath = "data"
        self.prompts_loc = 'prompts'
        self.JobDescriptionText = ''
        self.companyName = ''
        self.jobTitle = ''
        self.lifeSummary = ''
        self.headline = ''
        self.coverLetter = ''
        self.resumeSummary = ''
        self.skills = []
        self.jobs = []

        self.home_url =         "https://www.indeed.com/jobs?q=&l=Remote&vjk=7917c10f99e95728"
        self.home_url_pattern = "https://www.indeed.com/jobs?((.*))"
        self.Bad = -1
        self.FreeResponse = 0
        self.MultChoice = 1
        self.firstName = ''
        self.lastName = ""
        self.headline = ''
        self.phone_num = ''
        self.email = ''
        self.cityState = ''
        self.zip = ''

        self.load_life_summary()
        self.start_up()
        self.jobOpeningGenerator = self.process_job_openings()

    def today(self):
        # Get today's date
        today_date = datetime.date.today()

        # Format the date as "MM/DD/YYYY"
        formatted_date = today_date.strftime("%b %d, %Y")
        return formatted_date

    ##############################   START TRANSITION FUNCTIONS   ##################################

    def closeDialog(self):
        self.findAndClick(self.MATCH, self.ARIA_LABEL, "close icon", checkClosed=True)
    def newApp(self):
        #get next opening
        next(self.jobOpeningGenerator)
    def startApplication(self):
        # click on the Apply Now button if it is there
        self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="indeedApplyButton"]/div/span', checkNewTab=True, timeLimit=3)

    def updateContactInfo(self):
        return self.handleAddInfoPage()
    def startResume(self):
        return self.chooseToBuildIndeedResume()
    def addResume(self):
        return self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1, waitBeforeFinding=2)
    def backToDidContactInfo(self):
        pass
    def startContactInfo(self):
        return self.findAndClick(self.CONTAINS, self.ID, 'edit-contact-info', checkNewPage=True)
    def startSummary(self):
        # remove if already there
        delButs = self.findClosestRelatives(self.MATCH, self.TXT, 'Summary', self.CONTAINS, self.ID, 'delete',
                                            srchLvlLmt=2)
        if len(delButs) > 0:
            self.click_all(delButs)

        sumBut = self.findClosestRelatives(self.MATCH, self.TXT, 'Summary', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=sumBut, waitBeforeClicking=.7, checkNewPage=True)
    def startWorkExp(self):
        return self.do_work_exp()
    def startEdu(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.CONTAINS, self.ID, 'delete',
                                            srchLvlLmt=2)
        self.click_all(deletes)

        addEduBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=addEduBut, waitBeforeClicking=.7, checkNewPage=True)
    def startSkills(self):
        return self.do_skiils()
    def finishResume(self):
        return self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)
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
        return self.fillEducationInfo()
    def goBackToStartEdu(self):
        pass
    def doSkills(self):
        return self.do_skiils()
    def goBackToStartSkills(self):
        pass
    def doQuestions(self):
        return self.analyzeAndAnsQuestions()
    def keepGoing(self):
        #self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=2, waitBeforeClicking=1.1, checkNewPage=True)
        button = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Continue',
                                           self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=button, checkNewPage=True)
    def clickAddDocs(self):
        #  Find Supporting documents section and click on the add button
        addButton = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Supporting documents',
                                              self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=addButton, checkNewPage=True)
    def submitApp(self):
        return self.findAndClick(self.CONTAINS, self.TXT, 'Submit', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)
    def addDocs(self):
        self.do_cover_letter()
    def backToStart(self):
        pattern = self.escape_regex_special_chars(self.home_url_pattern)
        self.select_tab_by_url_pattern(pattern)
    def backToInit(self):
        pass
    ##############################    END TRANSITION FUNCTIONS   ##################################

    def process_job_openings(self):
        #  loop to go thru the different pages
        while True:
            #find the list of job openings
            openings = self.driver.find_elements(By.CSS_SELECTOR, '.css-5lfssm.eu4oa1w0')
            for opening in openings:
                self.smartClick(element=opening)

                #  get job info


                #rs = self.findClosestRelatives(self.CONTAINS, self.TXT, "s estimated salaries", self.CONTAINS, self.CLASS, 'CloseButton', limit=1)
                #if len(rs) == 1:
                #    self.click_all(rs)

                buttonElement = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="indeedApplyButton"]/div/span',
                                                  timeLimit=5, txtCond="$%^& Dont click yet &*(")

                if buttonElement is None:
                    # means this is not a job that you can apply from Indeed site
                    continue

                # extract job info
                #self.getPositionInfo()

                # load jobs and change job description based on the details of current job
                #self.load_jobs()

                # generate CL
                #self.generateCL()

                #generate skills
                #self.generateSkills()

                # generate headline
                #self.generateHeadline()

                #resume summary
                #self.generateSummary()

                yield



            self.findAndClick(self.MATCH, self.ARIA_LABEL,  'Next Page')

    def chooseToBuildIndeedResume(self):
        resButtonPath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[1]/div/div/div[2]/div[1]/div/div[2]/span[1]'
        editButtonPath = '//*[@id="edit-Ee5RAspBhdSgNHMSFzJyZg"]'

        #self.findAndClick(self.WHOLE, self.WHOLE, resButtonPath)
        self.findAndClick(self.CONTAINS, self.TXT, 'Indeed Resume', waitBeforeClicking=1)
        editButton = self.findAndClick(self.CONTAINS, self.TXT, 'Edit resume', timeLimit=1)
        return

    def handleAddInfoPage(self):
        potentialPageTitlePath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/h1'
        pathToContinue = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[2]/div/button/div'
        #  if We find it, We're not gonna click it.  just Wanted to knoW if it Was there
        title = self.findAndClick(self.WHOLE, self.WHOLE, potentialPageTitlePath, timeLimit=2, txtCond='@#%^&*()')
        if title is not None and title.text == 'Add your contact information':
            self.findAndClick(self.WHOLE, self.WHOLE, pathToContinue)

    def edit_contact_info(self):
        #self.findAndClick(self.CONTAINS, self.ID, 'edit-contact-info')
        fn_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'First name', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=fn_input)
        self.smartClick(element=fn_input)
        self.fillMoveOn(fn_input, self.firstName)

        ln_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Last name', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=ln_input)
        self.fillMoveOn(ln_input, self.lastName)

        head_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Headline', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=head_input)
        self.fillMoveOn(head_input, self.headline)  # need GPT

        phone_num_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Phone', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=phone_num_input)
        self.fillMoveOn(phone_num_input, self.phone_num)  # need GPT

        showPhone = self.findClosestRelatives(self.CONTAINS, self.ID, 'showPhoneNumber', self.WHOLE, self.WHOLE, '//input')[0]
        if not showPhone.is_selected():
            self.smartClick(element=showPhone)

        citystate_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'City, State', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=citystate_input)
        self.fillMoveOn(citystate_input, self.cityState)  # need GPT

        zip_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Postal code', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=zip_input)
        self.fillMoveOn(zip_input, self.zip )  # need GPT


        self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, checkNewPage=True)

    def do_summary(self):
        txtBoxPath = "//div[@role='textbox']"
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, self.resumeSummary) # need GPT
        return self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, waitBeforeClicking=.5, checkNewPage=True)

    def do_education(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        addEduBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=addEduBut, waitBeforeClicking=.7)

        return self.fillEducationInfo()

    def fillEducationInfo(self):
        # education level
        self.findFillMoveOn(self.CONTAINS, self.ID, 'educationLevel', "Bachelor's Degree")

        # field of study
        self.findFillMoveOn(self.CONTAINS, self.ID, 'fieldOfStudy', "Human Resources")

        # school name
        self.findFillMoveOn(self.CONTAINS, self.ID, 'school', "Chattahoochee Technical College")

        # school location
        self.findFillMoveOn(self.CONTAINS, self.ID, 'cityState', "Marietta, Georgia")

        # find the 4 drop downs
        drp_dwns = self.driver.find_elements('xpath', "//*[contains(@id, 'SelectFormField')]")
        frmMon, frmYr, toMon, toYr = tuple(drp_dwns)

        self.fillDropDown(frmMon, "Aug")
        self.fillDropDown(frmYr, "2017")
        self.fillDropDown(toMon, "May")
        self.fillDropDown(toYr, "2021")

        return self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)
        #self.finalizeResumeSection()

    def do_skiils(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Skills', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes, delayBeforeEach=.1)

        for skill in self.skills:
            addSkillBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Skills', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.smartClick(element=addSkillBut, waitBeforeClicking=.7, checkNewPage=True)
            self.findFillMoveOn(self.CONTAINS, self.ID, 'skillName', skill)
            self.finalizeResumeSection()

    def fillSkills(self):
        # generate a list of skills using chat GPT here
        for skill in self.skills:
            self.findFillEnter(self.CONTAINS, self.ID, 'new-skill-form', skill)

    def do_work_exp(self):
        #delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Work experience', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        files_in_subdir = os.listdir(self.dataPath)
        jobFiles = [self.dataPath + "\\" + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]

        # Adding a job
        #for filename in jobFiles:
        for job in self.jobs:
            addWorkBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Work experience', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.smartClick(element=addWorkBut, waitBeforeClicking=.7, checkNewPage=True)
            possExp = self.handleJob(job)


    def process_job_file(self, filename):
        jobFile = open(filename, "r")
        infoDict = {}
        jobFile.readline()
        for subject in ['title', 'comp', 'cityState', 'current', 'fromDate', 'toDate']:
            infoDict[subject] =  jobFile.readline().strip()
            jobFile.readline()
            jobFile.readline()

        #read the rest of the lines, that'll be the description
        rawDesc = jobFile.read().strip()
        mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()

        return infoDict

    def load_jobs(self):
        self.jobs.clear()
        files_in_subdir = os.listdir(self.dataPath)
        jobFiles = [self.dataPath + "\\" + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]

        for jobFile in jobFiles:
            self.jobs.append(self.process_job_file(jobFile))

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
        self.findFillMoveOn(self.CONTAINS, self.ID, 'jobTitle', title)

        # company name
        self.findFillMoveOn(self.CONTAINS, self.ID, 'company', comp)

        # city state
        self.findFillMoveOn(self.CONTAINS, self.ID, 'cityState', cityState)

        # current position
        if current:
            self.findAndClick(self.CONTAINS, self.ID, 'isCurrent')

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
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)  # need GPT
        return self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)

    def analyzeAndAnsQuestions(self):
        allPageQuestions = self.findAndClick(self.CONTAINS, self.CLASS, 'Questions-item',
                                             indInList=self.ALL, txtCond="#$%^&*(KJH")
        if len(allPageQuestions) > 0:
            url1 = self.driver.current_url
            # hit continue. Since no answers are chosen, this
            # wont be allowed and all the question error txt will appear
            self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1, waitBeforeClicking=.2)

            # if the url changed (meaning that our old responses were used)then just finish/return
            url2 = self.driver.current_url
            if url1 != url2:
                return  # nothing to do...questions already answered

            for questn in allPageQuestions:
                self.process_question(questn)

            self.keepGoing()

    def checkIfQuestionAlreadyAnswered(self, questn, type, answer_choices):
        if type == self.FreeResponse:
            prevTxt = answer_choices['inputBox'].get_attribute("value")
            return len(prevTxt) > 0
        elif type == self.MultChoice:
            # check if already answered
            checked = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@checked]', txtCond="asdf", findFrom=questn,
                                        timeLimit=1)
            return checked is not None
        else:
            return True


    def process_question(self, questn):  #//div[contains(@class, 'Questions-item')]
        questn_txt, answer_choices, errorTxt, type = self.extractQuestionInfo(questn)

        if self.checkIfQuestionAlreadyAnswered(questn, type, answer_choices):
            return

        #  get ans back from chat GPT
        ans = None
        if type == self.FreeResponse:
            # get chat GPT help with free response question
            mygpt = myGPT("free_response_question_prompts.txt", self.JobDescriptionText, self.lifeSummary, questn_txt)
            ans = mygpt.sendAll()

            answer_choices['inputBox'].send_keys(ans)
        elif type == self.MultChoice:
            #get chat GPT help
            mygpt = myGPT("mult_choice_question_prompts.txt", self.JobDescriptionText,
                          questn_txt, "\n".join(list(answer_choices.keys())))
            ans = mygpt.sendAll()

            self.smartClick(element=answer_choices[ans])
        elif type == self.Bad:
            # if optional is in question text, can just skip
            if '(optional)' in questn_txt:
                return
            else:
                print("non optional question but haven't seen this type... HELP")
                while True:
                    t.sleep(1)

    def extractQuestionInfo(self, questn):
        ans_dict = {
            # format =  "Yes": <obj>
            # format =  "No": <obj>
        }
        intermediate_ans_list = []
        questionText = ""
        # determine type  //*[@aria-label="Day and time option"]
        type = self.determine_question_type(questn)

        #get error text
        errorTxt = self.findAndClick(self.CONTAINS, self.ID, 'errorText', txtCond="$%^&*()", findFrom=questn, timeLimit=2)

        #get answer choices & question text
        if type == self.FreeResponse:
            ans_dict['inputBox'] = self.findAndClick(self.WHOLE, self.WHOLE, self.xpath_or(self.INPUT, self.TXTAREA) , findFrom=questn)
            questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn)
        elif type == self.MultChoice:
            intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
            ans_dict = { element.text : element for element in intermediate_ans_list}
            questionText = self.findAndClick(self.WHOLE, self.WHOLE, '//legend', findFrom=questn)
        elif type == self.Bad:
            questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn)



        return questionText.text, ans_dict, errorTxt, type

    def determine_question_type(self, questn):
        try:
            qChild = self.get_child(questn, 1, 1)
        except:
            return self.Bad

        num = self.num_children(qChild)
        listOfBad = self.findAndClick(self.MATCH, '@aria-label', 'Day and time option', findFrom=questn, indInList=self.ALL)
        if len(listOfBad) > 0:
            # then it's a question we don't want
            return self.Bad
        elif num == 2:
            return self.FreeResponse
        elif num == 1:
            return self.MultChoice


    def do_cover_letter(self):

        selection = self.findAndClick(self.CONTAINS, self.ID, 'write-cover-letter-selection-card')

        #use gpt to generate cover letter
        cv = None
        self.findFillMoveOn(self.WHOLE, self.WHOLE, self.TXTAREA, cv)

        self.findAndClick(self.CONTAINS, self.TXT, 'Update', travelUp=1)


    def addAnother(self):
        self.findAndClick(self.CONTAINS, self.TXT, 'Add another', travelUp=1)


    def finalizeResumeSection(self):
        self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1)

    def nextResumeSection(self):
        self.findAndClick(self.CONTAINS, self.TXT, 'Save and continue', travelUp=1)


    def load_life_summary(self):
        # purpose of '_' is to skip the explanation of the next line/section
        try:
            f = open("LifeSummary.txt", 'r')
            _, self.firstName = self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.lastName  =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.phone_num =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.email     =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.cityState =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)
            _, self.zip       =  self.nextNonBlankLine(f), self.nextNonBlankLine(f)

            #skip explanation for summary
            self.nextNonBlankLine(f)

            self.lifeSummary  =  f.read().strip()  # read the rest
        except:
            return


    def getPositionInfo(self):
        x = "//*[@data-testid='inlineHeader-companyName']"
        compNameEle = self.findAndClick(self.WHOLE, self.WHOLE, x, txtCond="dsfdsd324", timeLimit=1)
        self.companyName = compNameEle.text

        spanElement = self.findAndClick(self.WHOLE, self.WHOLE, "//span[contains(text(), '- job post')]", txtCond="33343vscads")
        titleElement = self.get_parent(spanElement )
        self.jobTitle = titleElement.text.split("\n")[0]

        jobDescElement = self.findAndClick(self.MATCH, self.ID, 'jobDescriptionText', txtCond='adsfdasf134')
        self.JobDescriptionText = jobDescElement.text

    def generateHeadline(self):
        mygpt = myGPT("headline_prompts.txt", self.JobDescriptionText)
        self.headline = mygpt.sendAll()

    def generateCL(self):
        mygpt = myGPT("cover_letter_prompts.txt", self.jobTitle, self.companyName,
                      self.JobDescriptionText, self.firstName, self.lastName,
                      self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                      self.email, self.cityState, self.today() )
        self.coverLetter = mygpt.sendAll()


    def generateSummary(self):
        mygpt = myGPT("summary_prompts.txt", self.coverLetter, self.firstName)
        self.resumeSummary = mygpt.sendAll()

    def generateSkills(self):
        mygpt = myGPT("skills_prompts.txt", self.JobDescriptionText, self.lifeSummary)
        skillsStrList = mygpt.sendAll()
        self.skills = skillsStrList.split(",")




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
        states = set(read_clean_lines(states_file))
        expected_environments = set(read_clean_lines(expected_environments_file))
        state_transitions_lines = read_clean_lines(state_transitions_file, dirty=True)

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
        extra_states_in_transitions = state_transitions_states - states
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
        with open(filename, "r") as f:
            return [line.strip() for line in f.readlines()  if line[:2] != "//" and len(line.strip()) > 0]

    def load_environments(self, filename):
        with open(filename, "r") as f:
            return [self.helper.escape_regex_special_chars(line.strip()) for line in f.readlines() if line[:2] != "//" and len(line.strip()) > 0 ]

    def load_transitions(self, filename):
        transitions = {}
        with open(filename, "r") as f:
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
        envPattern = self.envIsValid(environment)
        if not envPattern:
            print(f"Unexpected environment: {environment}")
            self.waitForever()
            return

        #checking that the transition file as made properly
        if self.envNextTrans(environment) is not None:
            if self.current_state in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern][self.current_state]
            else:
                funcName, next_state = self.transitions[envPattern]["default"]

            self.helper.reportAction(f"Calling function: {funcName}() in environment: {environment}", False)
            func = self.executeFunc(funcName)
            self.helper.reportAction(f"Transitioning  STATE from {self.current_state} to {next_state}", False)
            self.current_state = next_state
        else:
            print(f"No transition defined for environment: {environment}")
            self.waitForever()

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        return method_to_call()

    def waitForever(self):
        while True:
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