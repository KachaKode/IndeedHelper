import sqlite3

class Application:
    def __init__(self, applicantName_, datetime_,  platform_, companyName_, jobTitle_, jobDesc_, headline_, jobHist_, eduHist_, skills_, resumeSummary_, quest_ans_, cover_letter_):
        self.applicantName = applicantName_
        self.datetime = datetime_
        self.platform = platform_
        self.companyName = companyName_
        self.jobTitle = jobTitle_
        self.jobDesc = jobDesc_
        self.headline = headline_
        self.jobHist = eval(jobHist_)
        self.eduHist = eval(eduHist_)
        self.skills = eval(skills_)
        self.resumeSummary = resumeSummary_
        self.quest_ans = eval(quest_ans_)
        self.cover_letter = cover_letter_

    def toFile(self):
        contents = ""
        contents += "APPLICANT NAME\n"
        contents += f"{self.applicantName}\n"
        contents += "APPLICATION DATE\n"
        contents += f"{self.datetime}\n"
        contents += "APPLICATION PLATFORM\n"
        contents += f"{self.platform}\n"
        contents += "COMPANY NAME\n"
        contents += f"{self.companyName}\n"
        contents += "JOB TITLE\n"
        contents += f"{self.jobTitle}\n"
        contents += "JOB DESCRIPTION\n"
        contents += f"{self.jobDesc}\n"

        contents += "RESUME\n"
        contents += "Headline\n"
        contents += f"{self.headline}\n"

        for i, job in enumerate(self.jobHist):
            num = i + 1
            contents += f"Work History #{num}\n"
            contents += f"\ttitle:{job['title']}\n"
            contents += f"\tcompany:{job['comp']}\n"
            contents += f"\tlocation:{job['cityState']}\n"
            contents += f"\tFrom:{job['fromDate']}\n"
            contents += f"\tTo:{job['toDate']}\n"
            descLines = job['desc'].split("\n")
            for line in descLines:
                contents += f"\t\t{line}\n"

        for i, edu in enumerate(self.eduHist):
            num = i + 1
            contents += f"Edu History #{num}\n"
            contents += f"\ttitle:{edu['educationLevel']}\n"
            contents += f"\tcompany:{edu['fieldOfStudy']}\n"
            contents += f"\tlocation:{edu['school']}\n"
            contents += f"\tFrom:{edu['frmDate']}\n"
            contents += f"\tTo:{edu['toDate']}\n"

        contents += "Skills\n"
        for skill in self.skills:
            contents += f"\t{skill}\n"

        contents += "Summary\n"
        contents += f"{self.resumeSummary}\n"

        contents += "Questions And Answers\n"
        for i, q_a in enumerate(self.quest_ans):
            num = i + 1
            contents += f"\tQuestion #{num}\n"
            contents += f"\t{q_a['Question']}\n\n"
            contents += f"\tAnswer #{num}\n"
            contents += f"\t{q_a['Answer']}\n\n"

        contents += "COVER LETTER\n"
        contents += f"{self.cover_letter}\n"

        return contents

# if __name__ == "__main__":
#     desired_cols = """fullName, DateTime, Platform, companyName, jobTitle,
#                            JobDescriptionText, headline, jobHist, eduHist,
#                           skills, resumeSummary, QsAndAs, cover_letter"""
#     retrv_query = f"""SELECT {desired_cols} FROM applications WHERE user_id = ? AND companyName = ? AND jobTitle = ?"""
#
#     conn = sqlite3.connect('IndHelperDB.db')
#     cursor = conn.cursor()
#
#     id = int(input("User's DB ID?"))
#     compName = input("Company's Name:")
#     jobTitle = input("Job Title:")
#
#
#     cursor.execute(retrv_query, (id, compName, jobTitle) )
#
#     existing_record = cursor.fetchone()
#
#     app = Application( *tuple(existing_record))
#
#     print(app.toFile())
#
#     conn.close()

if __name__ == "__main__":
    desired_cols = """fullName, DateTime, Platform, companyName, jobTitle, 
                           JobDescriptionText, headline, jobHist, eduHist, 
                          skills, resumeSummary, QsAndAs, cover_letter"""
    retrv_query = f"""SELECT {desired_cols} FROM applications WHERE id = ?"""

    conn = sqlite3.connect('IndHelperDB.db')
    cursor = conn.cursor()

    id = int(input("Application ID?"))



    cursor.execute(retrv_query, (id,) )

    existing_record = cursor.fetchone()

    app = Application( *tuple(existing_record))

    print(app.toFile())

    conn.close()