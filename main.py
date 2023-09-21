# This is a sample Python script.

# GPT HELP:  https://chat.openai.com/c/aec09a74-238d-4f97-b49a-b6ca98e1d810

#Note  need to set up dummy chrome profile if you want browser to remember things

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import os, re
import inspect
import time as t


class SeleniumWrap:

    def __init__(self):
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
        self.TXTAREA = '//textarea'
        self.ARIA_LABEL = '@aria-label'
        self.DELTA_WAIT = .2
        self.ALL = float('inf')
    def start_up(self):
        chrome_options = Options()
        chrome_options.add_argument(self.chrome_profile)
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.get(self.home_url)

    def click_all(self, list_of_elements):
        for element in list_of_elements:
            self.delayedClick(element)

    def clickChecker(self, element, checked, cond):
        try:  # if a new page is expected, then element might become unclickable
            self.delayedClick(element)
        except:
            # it's okay if an exception happens here.  Since we previously found the
            # element, we know it's only unclickable here because the page changed
            pass
        t.sleep(self.DELTA_WAIT)
        if cond():
            checked[0] = True

    def clickAttempt(self, elementXpath, indInList, travelUp, txtCond, waitBeforeClicking,
                     checkNewPage, url_at_start, checkNewTab, num_tabs_at_start, findFrom, waitBeforeFinding):

        t.sleep(waitBeforeFinding)

        # if looking for a list of all matches then don't need to click
        if indInList == self.ALL:
            matches = findFrom.find_elements('xpath', elementXpath)
            self.reportAction(f"returning {len(matches)} matches for {elementXpath}!")
            return matches


        element = findFrom.find_elements('xpath', elementXpath)[indInList]
        # travel upwards if specified...
        for i in range(travelUp, 0, -1):
            element = self.get_parent(element)

        if txtCond == '' or txtCond == element.text:
            checked = [False]
            while not checked[0]:
                if waitBeforeClicking > 0:
                    self.delayedClick(element, waitBeforeClicking, checked)
                elif checkNewPage:
                    cond = lambda: url_at_start != self.driver.current_url
                    self.clickChecker(element, checked, cond)
                elif checkNewTab:
                    cond = lambda: num_tabs_at_start != len(self.driver.window_handles)
                    self.clickChecker(element, checked, cond)
                else:
                    self.delayedClick(element)
                    checked[0] = True

            self.reportAction(f"clicked {elementXpath} successfully!")
        else:
            self.reportAction(f"found element {elementXpath} but did not click because text did not match: {txtCond}")
        return element

    def delayedClick(self, element, waitBeforeClicking=.05, checked=None):
        #attempt to scroll element to center screen
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        t.sleep(max(waitBeforeClicking, .05))
        if checked is not None:
           checked[0] = True
        element.click()
        #self.driver.execute_script("arguments[0].click();", element)

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

    def findAndClick(self, type, what, elementXpath, indInList=0, travelUp=0, timeLimit=10, txtCond = '',
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0 ):
        root = ""
        if findFrom is None:
            findFrom = self.driver
        else:
            root = "."

        num_tabs_at_start = len(self.driver.window_handles)
        url_at_start = self.driver.current_url

        if type == self.CONTAINS:
            elementXpath = f"{root}//*[contains({what}, '{elementXpath}')]"
        elif type == self.WHOLE:
            elementXpath = elementXpath[:2].replace("//", f"{root}//") + elementXpath[2:]
        elif type == self.MATCH:
            elementXpath = f"{root}//*[{what}='{elementXpath}']"

        element = None

        spentWaiting = [0]
        while True:
            try:
                element = self.clickAttempt(elementXpath, indInList, travelUp, txtCond,
                                            waitBeforeClicking, checkNewPage, url_at_start,
                                            checkNewTab, num_tabs_at_start, findFrom, waitBeforeFinding)
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
        self.delayedClick(drpElement)
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

    def reportAction(self, actionMsg):
        print(actionMsg)
        stack = inspect.stack()
        listFuncCalls = [frame.function for frame in stack]
        listFuncCalls.pop(0)
        funcStack = ' | '.join(listFuncCalls)
        print(f"\tFunction Stack: {funcStack}\n")

    def getCurrentEnv(self):
        currentEnv = ""
        #  first handle URL
        url = self.driver.current_url

        #  check if a dialog box is present
        dialogBox = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@role="dialog" and @aria-modal="true"]',
                                      txtCond="#$%^&*", timeLimit=1, waitBeforeFinding=.7)
        # if so  get the text
        if dialogBox is not None:
            mainText = dialogBox.text
            currentEnv = f"{url}|{mainText}"
        # if not, get the first <title>\
        else:
            titleElement = self.findAndClick(self.WHOLE, self.WHOLE, '//title',
                                      txtCond="#$%^&*", timeLimit=1, waitBeforeFinding=.7)
            currentEnv = f"{url}|{titleElement.text}"

        return currentEnv



class IndeedHelper(SeleniumWrap):
    def __init__(self):
        super().__init__()
        self.dataPath = "data"
        self.home_url = "https://www.indeed.com/jobs?q=&l=Remote&vjk=7917c10f99e95728"
        self.Bad = -1
        self.FreeResponse = 0
        self.MultChoice = 1
        self.firstName = 'cv'
        self.lastName = "ag"

    def process_job_openings(self):
        #find the list of job openings
        openings = self.driver.find_elements(By.CSS_SELECTOR, '.css-5lfssm.eu4oa1w0')
        for opening in openings:
            self.delayedClick(opening)

            rs = self.findClosestRelatives(self.CONTAINS, self.TXT, "s estimated salaries", self.CONTAINS, self.CLASS, 'CloseButton', limit=1)
            if len(rs) == 1:
                self.click_all(rs)


            #click on the Apply Now button if it is there
            buttonElement = self.findAndClick(self.WHOLE, self.WHOLE,  '//*[@id="indeedApplyButton"]/div/span', timeLimit=5, checkNewTab=True)
            if buttonElement is None:
                # means this is not a job that you can apply from Indeed site
                continue

            #browser has already switched tabs but program still needs to switch
            all_tabs = self.driver.window_handles
            self.driver.switch_to.window(all_tabs[-1])

            self.handleAddInfoPage()

            if self.chooseToBuildIndeedResume():
                continue

            self.fillEducationInfo()

            self.nextResumeSection()

            self.deleteAllPrevJobs()

            self.fillPrevJobsInfo()

            self.nextResumeSection()

            self.fillSkills()

    def chooseToBuildIndeedResume(self):
        resButtonPath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[1]/div/div/div[2]/div[1]/div/div[2]/span[1]'
        editButtonPath = '//*[@id="edit-Ee5RAspBhdSgNHMSFzJyZg"]'

        #self.findAndClick(self.WHOLE, self.WHOLE, resButtonPath)
        self.findAndClick(self.CONTAINS, self.TXT, 'Indeed Resume', waitBeforeClicking=1)
        editButton = self.findAndClick(self.CONTAINS, self.TXT, 'Edit resume', timeLimit=1)
        if editButton is not None:
            # edit contact info
            self.edit_contact_info()

            self.do_summary()

            self.do_work_exp()

            self.do_education()

            self.do_skiils()

            self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1, waitBeforeClicking=.7)

            self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1, waitBeforeFinding=2)

            self.doQuestions()

            # skip the other applications
            self.findAndClick(self.CONTAINS, self.TXT, 'Continue to app', travelUp=1, timeLimit=2)

            #  skip the relevant job high light
            highlightTitle  = self.findAndClick(self.CONTAINS, self.TXT, 'Highlight a job that shows rel', timeLimit=1, txtCond="$%^&*(")
            if highlightTitle is not None:
                self.findAndClick(self.CONTAINS, self.TXT, 'Continue', travelUp=1)

            self.do_cover_letter()

            self.findAndClick(self.CONTAINS, self.TXT, 'Submit', travelUp=1)

            return True

        self.findClosestRelatives(self.CONTAINS, self.TXT, 'Work experience', self.CONTAINS, self.ID, 'delete')
        self.findAndClick(self.CONTAINS, self.ID, 'edit', timeLimit=2) #'//*[@id="return-to-page"]
        return False

    def handleAddInfoPage(self):
        potentialPageTitlePath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/h1'
        pathToContinue = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[2]/div/button/div'
        #  if We find it, We're not gonna click it.  just Wanted to knoW if it Was there
        title = self.findAndClick(self.WHOLE, self.WHOLE, potentialPageTitlePath, timeLimit=2, txtCond='@#%^&*()')
        if title is not None and title.text == 'Add your contact information':
            self.findAndClick(self.WHOLE, self.WHOLE, pathToContinue)

    def edit_contact_info(self):
        self.findAndClick(self.CONTAINS, self.ID, 'edit-contact-info')
        fn_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'First name', self.WHOLE, self.WHOLE, '//input')[0]
        self.delayedClick(fn_input)
        self.delayedClick(fn_input)
        self.fillMoveOn(fn_input, self.firstName)

        ln_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Last name', self.WHOLE, self.WHOLE, '//input')[0]
        self.delayedClick(ln_input)
        self.fillMoveOn(ln_input, self.lastName)

        head_input = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Headline', self.WHOLE, self.WHOLE, '//input')[0]
        self.delayedClick(head_input)
        self.fillMoveOn(head_input, "some head line")  # need GPT

        self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1)

    def do_summary(self):
        #remove if already there
        delButs = self.findClosestRelatives(self.MATCH, self.TXT, 'Summary', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        if len(delButs) > 0:
            self.click_all(delButs)

        sumBut = self.findClosestRelatives(self.MATCH, self.TXT, 'Summary', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.delayedClick(sumBut, waitBeforeClicking=.7)
        txtBoxPath = "//div[@role='textbox']"
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, "summary idk") # need GPT
        self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, waitBeforeClicking=.5)

    def do_education(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        addEduBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.delayedClick(addEduBut, waitBeforeClicking=.7)

        self.fillEducationInfo()

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

        self.finalizeResumeSection()

    def do_skiils(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Skills', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        list_of_skills = self.generateSkills()
        for skill in list_of_skills:
            addSkillBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Skills', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.delayedClick(addSkillBut, waitBeforeClicking=.7)
            self.findFillMoveOn(self.CONTAINS, self.ID, 'skillName', skill)
            self.finalizeResumeSection()

    def generateSkills(self):
        return ['d', 'q', 'y', 'x'] #  need GPT

    def fillSkills(self):
        # generate a list of skills using chat GPT here
        list_of_skills = self.generateSkills()
        for skill in list_of_skills:
            self.findFillEnter(self.CONTAINS, self.ID, 'new-skill-form', skill)

    def do_work_exp(self):
        #delete all prior
        deletes = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Work experience', self.CONTAINS, self.ID, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        files_in_subdir = os.listdir(self.dataPath)
        jobFiles = [self.dataPath + "\\" + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]

        # Adding a job
        for filename in jobFiles:
            addWorkBut = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Work experience', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.delayedClick(addWorkBut, waitBeforeClicking=.7)
            self.handleJob(filename)

    def process_job_file(self, filename):
        jobFile = open(filename, "r")
        infoList = []
        jobFile.readline()
        for i in range(6):
            infoList.append(   jobFile.readline().strip()    )
            jobFile.readline()
            jobFile.readline()

        #read the rest of the lines, that'll be the description
        infoList.append(   jobFile.read().strip()    )
        return tuple(infoList)

    def deleteAllPrevJobs(self):
        t.sleep(1)
        delButs = self.driver.find_elements("xpath", "//*[contains(@id, 'delete')]")
        for delB in delButs:
            self.delayedClick(delB)

            if delB == delButs[-1]:
                # only want to do this after deleting the last job.  If we didn't have to delete anyting, then don't need
                # to click on this "Add another" button
                self.addAnother()

    def fillPrevJobsInfo(self):
        files_in_subdir = os.listdir(self.dataPath)
        jobFiles = [self.dataPath + "\\" + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]
        desc_xp = '/html/body/div[2]/div/main/div/div/div[2]/form/div[2]/div[8]/div/div/div/div/div/div[2]'

        # Adding a job
        for filename in jobFiles:
            self.handleJob(filename)

            self.finalizeResumeSection()

            # check if there are still more job files to process
            if filename != jobFiles[-1]:
                self.addAnother()

    def handleJob(self, filename):
        title, comp, cityState, current, fromDate, toDate, desc = self.process_job_file(filename)
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
        self.findAndClick(self.CONTAINS, self.TXT, 'Save', travelUp=1, waitBeforeClicking=1)

    def doQuestions(self):
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

            self.finalizeResumeSection()

    def process_question(self, questn):  #//div[contains(@class, 'Questions-item')]
        questn_txt, answer_choices, errorTxt, type = self.extractQuestionInfo(questn)

        #  get ans back from chat GPT
        ans = None
        if type == self.FreeResponse:
            # get chat GPT help
            self.delayedClick(answer_choices[ans])
        elif type == self.MultChoice:
            #get chat GPT help
            answer_choices['inputBox'].send_keys(ans)
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
            ans_dict['inputBox'] = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, findFrom=questn)
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
        #  Find Supporting documents section and click on the add button
        addButton = self.findClosestRelatives(self.CONTAINS, self.TXT, 'Supporting documents',
                                              self.CONTAINS, self.TXT, 'Add')[0]
        self.delayedClick(addButton)
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


    def run(self):
        self.start_up()

        input("Press enter when you have signed in.")

        #for each page, process the job openings
        self.process_job_openings()


class StateMachine:
    def __init__(self, helper : SeleniumWrap ):
        self.states = self.load_states("States.txt")
        self.expected_environments = self.load_environments("ExpectedEnvironments.txt")
        self.transitions = self.load_transitions("StateTransitions.txt")
        self.current_state = self.states[0]
        self.helper = helper

    @staticmethod
    def load_states(filename):
        with open(filename, "r") as f:
            return [line.strip() for line in f.readlines()  if line[:2] != "//" and len(line.strip()) > 0]

    @staticmethod
    def load_environments(filename):
        with open(filename, "r") as f:
            return [line.strip() for line in f.readlines() if line[:2] != "//" and len(line.strip()) > 0 ]

    @staticmethod
    def load_transitions(filename):
        transitions = {}
        with open(filename, "r") as f:
            lines = f.readlines()
            env = None
            for line in lines:
                line = line.strip()
                if line in self.expected_environments:
                    env = line
                else:
                    state, func, next_state = line.split("--")
                    state = state.strip()
                    func = func.strip("() ")
                    next_state = next_state.strip("-> ")
                    if env not in transitions:
                        transitions[env] = {}
                    transitions[env][state] = (func, next_state)
        return transitions

    def envIsValid(self):
        return any(re.match(pattern.lower(), environment.lower())
                   for pattern in self.expected_environments)

    def envHasTrans(self):
        return any(re.match(pattern.lower(), environment.lower())
                   for pattern in self.transitions.keys())

    def transition(self, environment):
        if not self.envIsValid():
            print(f"Unexpected environment: {environment}")
            self.waitForever()
            return

        if self.envHasTrans():
            if self.current_state in self.transitions[environment]:
                funcName, next_state = self.transitions[environment][self.current_state]
            else:
                funcName, next_state = self.transitions[environment]["default"]

            print(f"Calling function: {funcName}")
            self.executeFunc(funcName)
            self.current_state = next_state
            print(f"Transitioned to state: {self.current_state}")
        else:
            print(f"No transition defined for environment: {environment}")
            self.waitForever()

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        method_to_call()

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
    sm = StateMachine(IndeedHelper())
    sm.run()


#ih = IndeedHelper()
#ih.run()