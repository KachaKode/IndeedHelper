import openai
import datetime




class myGPT:
    def __init__(self, setupInfo, *args, inputPath=".//input", promptsPath=".//prompts"):
        self.nextMessages = []
        self.checks = {}
        self.checkNOTs = {}
        self.prompts_str = ""
        self.keep = False
        self.checkerLinesToProcess = 0
        self.combineLinesMarker = "**KEEP**ALL**TOGETHER**"
        self.separateLinesMarker = "**END**ALL**TOGETHER**"
        self.checkerMarker = "&&CHECK&&"
        self.checkerMarkerNot = "&&CHECK&&NOT&&"
        self.inputPath = inputPath
        self.promptsPath = promptsPath
        self.messages = [{"role": "system", "content":
            "You are a intelligent assistant."}]
        self.loadAPIKey()

        print(f"starting: {setupInfo} @ {datetime.datetime.now().strftime('%H:%M:%S')}")
        if type(setupInfo) == dict:
            self.setupForStudent(setupInfo)
        elif type(setupInfo) == list:
            self.nextMessages.extend(setupInfo)
        elif type(setupInfo) == str:
            self.processMsgFile(setupInfo, *args)

    def processMsgFile(self, file, *args):
        f = open(f"{self.promptsPath}\\{file}", 'r')
        self.prompts_str = ""
        prompts = []
        self.keep = False
        self.checkerLinesToProcess = 0
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = line.strip()
            if self.contPlusAction(i, line, lines):
                continue
            self.prompts_str += line + {False:'*\n*', True:"\n"}[self.keep]

        #remove the last new line
        prompts_str = self.prompts_str[:-3]

        for arg in args:
            prompts_str = prompts_str.replace(f"PLACE&&HOLDER&&", arg, 1)
        self.nextMessages.extend(prompts_str.split("*\n*"))
        f.close()

    def contPlusAction(self, i, line, lines):
        if len(line) == 0 and not self.keep:
            return True
        if self.checkerLinesToProcess > 0:
            self.checkerLinesToProcess -= 1
            return True
        if "//" == line[:2]:
            return True
        if self.combineLinesMarker in line:
            self.keep = True
            return True
        elif self.separateLinesMarker in line:
            self.keep = False
            self.prompts_str += '*\n*'
            return True
        elif self.checkerMarker in line:
            badStrs = lines[i + 1].strip().split("|")
            for badStr in badStrs:
                self.checks[badStr] = lines[i + 2]
            self.resetCheckerLinesVar()
            return True
        elif self.checkerMarkerNot in line:
            reqStrs = lines[i + 1].strip().split("|")
            for reqStr in reqStrs:
                self.checkNOTs[reqStr] = lines[i + 2]
            self.resetCheckerLinesVar()
            return True
        return False

    def resetCheckerLinesVar(self):
        # set it equal to 2 so that the next 2 lines are skipped
        self.checkerLinesToProcess = 2

    def sendAll(self):
        for nuMsg in self.nextMessages:
            self.send(nuMsg)

        self.doChecks()

        self.doCheckNots()

        print(f"done... @ {datetime.datetime.now().strftime('%H:%M:%S')}")

        return self.reply

    def doChecks(self):
        '''this function checks for the presense of sub strings in the reply
        that are NOT suppsoed to be in the reply.  If it finds one of these forbidden
        substrings, it sends chatgpt a message about it '''
        while True:
            for badSubStr, responseToBadStr in self.checks.items():
                if badSubStr in self.reply:
                    self.send(responseToBadStr)
                    break
            else:
                # This else block is executed if no bad substring was found
                # Add code here to handle the case when nothing bad is found
                break
    def doCheckNots(self):
        '''this function checks for the presense of sub strings in the reply
        that ARE suppsoed to be in the reply.  If it does not find one
        of these required substrings, it sends chatgpt a message about it '''

        while True:
            for reqSubStr, responseToNoReqStr in self.checkNOTs.items():
                if reqSubStr not in self.reply:
                    self.send(responseToNoReqStr)
                    break
            else:
                # This else block is executed if no bad substring was found
                # Add code here to handle the case when nothing bad is found
                break  # it's supposd to be in-line w the 'for', not the 'if'.
    def setupForStudent(self, studentInfo):
        studentName, studentSubject, studentMsg = studentInfo
        self.studentMsg = studentMsg
        self.studentName = studentName
        self.studentSubject = studentSubject

        self.loadPrompt()

        self.loadQualification()

        self.loadFormatPrompt()

    def loadAPIKey(self):
        api_key_file = open(f"{self.inputPath}\\api_key.txt")
        openai.api_key = api_key_file.read()
        api_key_file.close()

    def loadPrompt(self):
        initPromptFile = open(f"{self.inputPath}\\initialPrompt.txt", "r")
        self.promptContent = initPromptFile.read()
        initPromptFile.close()

    def loadQualification(self):
        qualificationPromptFile = open(f"{self.inputPath}qualificationPrompt.txt", "r")
        qualificationQuoteFile  = open(f"{self.inputPath}qualificationQuote.txt", "r")
        self.qualQuote = qualificationQuoteFile.read().replace("REPLACE_NUM_1", self.studentSubject)
        self.qualPrompt = qualificationPromptFile.read().replace("REPLACE_NUM_1", self.qualQuote)
        qualificationPromptFile.close()
        qualificationQuoteFile.close()

    def loadFormatPrompt(self):
        formatPromptFile = open(f"{self.inputPath}formatPrompt.txt")
        self.formatPrompt = formatPromptFile.read()
        formatPromptFile.close()

    def send(self, nu_msg=None):
        self.messages.append(
            {"role": "user", "content": nu_msg},
        )
        chat = openai.ChatCompletion.create(
            # model="gpt-3.5-turbo", messages=messages
            model="gpt-3.5-turbo-16k-0613", messages=self.messages
        )

        self.reply = chat.choices[0].message.content
        self.messages.append({"role": "assistant", "content": self.reply})

    def checkQualificationAdded(self):
        quotes = self.qualQuote.split("  ")
        quote1, quote2 = quotes[0].lower(), quotes[-1].lower()
        while quote1 not in self.reply.lower() or quote2 not in self.reply.lower():
            # inform chat GPT that they made a mistake including the quote
            message = "I told you the quote had to be included verbatim."
            message += "  Give me the revised message only, no extra greeting or apology or quotes etc."
            self.send()

    def addGreetAndClose(self):
        greeting = f"Hey {self.studentName}!\n"
        self.reply = greeting + self.reply + "\nBest regards,\nMarcus"


    def runChat(self):
        # first, send the initial prompt
        self.message = self.promptContent.replace("REPLACE_NUM_1", self.studentSubject)
        self.message = self.message.replace("REPLACE_NUM_2", self.studentName)
        self.message = self.message.replace("REPLACE_NUM_3", self.studentMsg)
        self.send()

        #next, incorporate the qualification / brag quote
        self.message = self.qualPrompt.replace("REPLACE_NUM_1", self.studentSubject)
        self.send()

        #check the qualification was added correctly
        self.checkQualificationAdded()

        # make sure the message is formatted neatly
        self.message = self.formatPrompt
        self.send()

        self.addGreetAndClose()

        return self.reply


if __name__ == "__main__":
    name = "Aarti"
    sub = "Python"
    msg = """I am doing intro to Information Security. My first assignment needs Wireshark and python and am not familiar with either. I need help to understand how to use these two and then how to incorporate them in my assignment. Assignment is due on Friday."""

    mgpt = myGPT(name, sub, msg)

    response = mgpt.runChat()

    print(response)