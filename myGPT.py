import openai


class myGPT:
    def __init__(self, setupInfo, inputPath=".//input//"):
        self.nextMessages = []
        self.inputPath = inputPath
        self.messages = [{"role": "system", "content":
            "You are a intelligent assistant."}]
        self.loadAPIKey()


        if type(setupInfo) == dict:
            self.setupForStudent(setupInfo)
        elif type(setupInfo) == list:
            self.nextMessages.extend(setupInfo)
        elif type(setupInfo) == str:
            self.processMsgFile(setupInfo)

    def processMsgFile(self, file):
        f = open(file, 'r')
        for line in f.readlines():
            if len(line.strip()) == 0:
                continue
            self.nextMessages.append(line)
        f.close()

    def sendAll(self):
        for nuMsg in self.nextMessages:
            self.message = nuMsg
            self.send()
        return self.reply

    def setupForStudent(self, studentInfo):
        studentName, studentSubject, studentMsg = studentInfo
        self.studentMsg = studentMsg
        self.studentName = studentName
        self.studentSubject = studentSubject

        self.loadPrompt()

        self.loadQualification()

        self.loadFormatPrompt()

    def loadAPIKey(self):
        api_key_file = open(f"{self.inputPath}api_key.txt")
        openai.api_key = api_key_file.read()
        api_key_file.close()

    def loadPrompt(self):
        initPromptFile = open(f"{self.inputPath}initialPrompt.txt", "r")
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

    def send(self):
        if self.message:
            self.messages.append(
                {"role": "user", "content": self.message},
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


name = "Aarti"
sub = "Python"
msg = """I am doing intro to Information Security. My first assignment needs Wireshark and python and am not familiar with either. I need help to understand how to use these two and then how to incorporate them in my assignment. Assignment is due on Friday."""

mgpt = myGPT(name, sub, msg)

response = mgpt.runChat()

print(response)