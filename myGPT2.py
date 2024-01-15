import openai
import datetime
import time as t
import concurrent.futures

#  https://chat.openai.com/c/28f417b1-35f8-44d3-8515-dd5b64cf7395


class myGPT:
    def __init__(self, setupInfo, *args, inputPath=".//input", promptsPath=".//prompts", chatTimeOut=300, version=2):
        self.nextMessages = []
        self.checks = {}
        self.checkNOTs = {}
        self.prompts_str = ""
        self.keep = False
        self.need_redo = False
        self.checkerLinesToProcess = 0
        self.combineLinesMarker = "**KEEP**ALL**TOGETHER**"
        self.separateLinesMarker = "**END**ALL**TOGETHER**"
        self.checkerMarker = "&&CHECK&&"
        self.checkerMarkerNot = "&&CHECK&&NOT&&"
        self.placeHoldMarker = "PLACE&&HOLDER&&"
        self.place_vals = []
        self.inputPath = inputPath
        self.promptsPath = promptsPath
        self.context = [] #{"role": "system", "content":
            #"You are a intelligent assistant."}]
        self.loadAPIKey()
        self.chatTimeOut = chatTimeOut

        self.logFile = open("logger.txt", 'a')

        now = datetime.datetime.now()
        doneBy = now + datetime.timedelta(seconds=self.chatTimeOut)
        print(f"starting: {setupInfo} @ {now.strftime('%H:%M:%S')} ... (will time out @ {doneBy.strftime('%H:%M:%S')})")
        if type(setupInfo) == dict:
            self.setupForStudent(setupInfo)
        elif type(setupInfo) == list:
            self.nextMessages.extend(setupInfo)
        elif type(setupInfo) == str:
            if version == 2:
                self.processMsgFile2(setupInfo, *args)
            else:
                self.processMsgFile(setupInfo, *args)

    def log(self, msg):
        self.logFile.write(msg)
        self.logFile.flush()

    def setAllPlaceVals(self, string):
        while self.placeHoldMarker in string:
            placeVal = self.place_vals.pop(0)
            string = string.replace(self.placeHoldMarker, placeVal, 1)
        return string.replace("&&nu_line&&", "\n")

    def processMsgFile2(self, file, *args):
        self.log("starting to process msg file")
        f = open(f"{self.promptsPath}\\{file}", 'r')
        self.prompts_str = ""
        self.place_vals = list(args)
        prompts = []
        self.keep = False
        self.checkerLinesToProcess = 0
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = line.strip()
            lineContainer = [line]
            if self.contPlusAction(i, lineContainer, lines):
                continue
            line = lineContainer[0]
            self.prompts_str += line + {False:'*\n*', True:"\n"}[self.keep]

        #remove the last new line
        prompts_str = self.prompts_str[:-3]

        prompts_list = prompts_str.split("*\n*")

        newMessage = prompts_list.pop(-1)

        self.context.extend([{"role": "system", "content": cont} for cont in prompts_list])

        self.nextMessages.append(newMessage)
        f.close()
        self.log("finished processing msg file")

    def processMsgFile(self, file, *args):
        self.log("starting to process msg file")
        self.context.append({"role": "system", "content":
            "You are a intelligent assistant."})
        f = open(f"{self.promptsPath}\\{file}", 'r')
        self.prompts_str = ""
        self.place_vals = list(args)
        prompts = []
        self.keep = False
        self.checkerLinesToProcess = 0
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = line.strip()
            lineContainer = [line]
            if self.contPlusAction(i, lineContainer, lines):
                continue
            line = lineContainer[0]
            self.prompts_str += line + {False:'*\n*', True:"\n"}[self.keep]

        #remove the last new line
        prompts_str = self.prompts_str[:-3]

        self.nextMessages.extend(prompts_str.split("*\n*"))
        f.close()
        self.log("finished processing msg file")

    def contPlusAction(self, i, lineContainer, lines):
        if len(lineContainer[0]) == 0 and not self.keep:
            return True
        if self.checkerLinesToProcess > 0:
            self.checkerLinesToProcess -= 1
            return True
        if "//" == lineContainer[0][:2]:
            return True

        #replace the placeholders, if any
        lineContainer[0] = self.setAllPlaceVals(lineContainer[0])

        if self.combineLinesMarker in lineContainer[0]:
            self.keep = True
            return True
        elif self.separateLinesMarker in lineContainer[0]:
            self.keep = False
            self.prompts_str += '*\n*'
            return True
        elif self.checkerMarkerNot in lineContainer[0]:
            reqStrs = lines[i + 1].strip().split("&&OR&&")
            chks = []
            for reqStr in reqStrs:
                and_grp_dict = {}
                for and_member in reqStr.strip().split("&&AND&&"):
                    and_grp_dict[and_member] = and_grp_dict.setdefault(and_member, 0) + 1
                chks.append(tuple( and_grp_dict.items() ) )
                #chks.append( tuple(reqStr.strip().split("&&AND&&")) )
            self.checkNOTs[tuple(chks)] = self.setAllPlaceVals(lines[i + 2])
            self.resetCheckerLinesVar()
            return True
        elif self.checkerMarker in lineContainer[0]:
            badStrs = lines[i + 1].strip().split("&&OR&&")
            chks = []
            for badStr in badStrs:
                and_grp_dict = {}
                for and_member in badStr.strip().split("&&AND&&"):
                    and_grp_dict[and_member] = and_grp_dict.setdefault(and_member, 0) + 1
                chks.append(tuple(and_grp_dict.items()))
                #chks.append(tuple(badStr.strip().split("&&AND&&")))
            self.checks[tuple(chks)] = self.setAllPlaceVals(lines[i + 2])
            self.resetCheckerLinesVar()
            return True

        return False

    def resetCheckerLinesVar(self):
        # set it equal to 2 so that the next 2 lines are skipped
        self.checkerLinesToProcess = 2

    def sendAll(self):
        self.need_redo = False
        self.log("starting to send messages")
        for nuMsg in self.nextMessages:
            self.log("sending msg to chatGPT server")
            self.send(nuMsg)
            self.log("sent message to chatGPT server")
        self.log("done sending messages")

        self.log("starting bad checks")
        self.doChecks()
        self.log("done bad checks")

        self.log("starting good checks")
        self.doCheckNots()
        self.log("done good checks")

        print(f"done... @ {datetime.datetime.now().strftime('%H:%M:%S')}")

        return self.reply


    def checkOrGroup(self, OrTuple, superstring, checkForPresence=True):
        if checkForPresence:
            return any(all(superstring.count(req[0]) >= req[1] for req in AndTuple) for AndTuple in OrTuple)
        else:
            return any(all(superstring.count(req[0]) < req[1] for req in AndTuple) for AndTuple in OrTuple)

    def doChecks(self):
        '''this function checks for the presense of sub strings in the reply
        that are NOT suppsoed to be in the reply.  If it finds one of these forbidden
        substrings, it sends chatgpt a message about it '''
        counts = {}
        while True:
            for badOrGrp, responseToBadStr in self.checks.items():
                if self.checkOrGroup(badOrGrp, self.reply):
                    self.send(responseToBadStr)
                    counts[badOrGrp] = counts.setdefault(badOrGrp, 0) + 1
                    if counts[badOrGrp] > 5:
                        print("\tThere might be an issue, keep on repeating the same check")
                        self.need_redo = True
                        return
                    print(f"\tGPT made mistake having this: {badOrGrp}, had 2 send this: {responseToBadStr} @ {datetime.datetime.now().strftime('%H:%M:%S')}")
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
            for reqOrGroup, responseToNoReqStr in self.checkNOTs.items():
                if self.checkOrGroup(reqOrGroup, self.reply, checkForPresence=False):
                    self.send(responseToNoReqStr)
                    print(f"\tGPT made mistake not having this: {reqOrGroup}, gtta send this: {responseToNoReqStr} @ {datetime.datetime.now().strftime('%H:%M:%S')}")
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
        #pause for 2 secs so don't get jammed up...?
        t.sleep(5)

        self.context.append(
            {"role": "user", "content": nu_msg},
        )
        secs = 5
        while True:
            try:
                chat = self.executeWrapperWithTimeOut()
                break
            except Exception as e:
                print(f"\tRan into {e} error so waiting {secs} seconds and trying again")
                t.sleep(secs)
                secs *= 2

        self.reply = chat.choices[0].message.content
        self.context.append({"role": "assistant", "content": self.reply})

    def executeWrapperWithTimeOut(self):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            print(f"\tAttempting the future retreival")
            future = executor.submit(self.sendChatWrapper)
            try:
                result = future.result(timeout=self.chatTimeOut)  # 600 seconds = 10 minutes
                return result
            except concurrent.futures.TimeoutError:
                print(f"\tChat Completion timed out. after {self.chatTimeOut} secs.. Restarting... in 1 min")
                # If you want to retry the function after a timeout, you can call the function again here
                t.sleep(60)
                print("\tRestarting now")
                return self.executeWrapperWithTimeOut()
            except Exception as e:
                # Handle other exceptions as needed
                raise e

    def sendChatWrapper(self):
        print("\tAttempting Completion")
        return openai.ChatCompletion.create(
            # model="gpt-3.5-turbo", messages=messages
            model="gpt-3.5-turbo-16k-0613", messages=self.context
        )

    def sendFromFile(self, filename, *args):
        self.nextMessages.clear()
        self.processMsgFile(filename, *args)
        return self.sendAll()
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