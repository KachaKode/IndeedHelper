import sqlite3
import re
import os
from selenium import webdriver


"""
import main 
sw = main.SeleniumWrap("https://docs.google.com/document/u/0/", "https://docs.google.com/document/u/0/", "C:\\Users\\PJuJu\\AppData\\Local\\Google\\Chrome\\User Data\\Default")

"""


def nextNonBlankLine(file_handler):
    # This function will yield non-blank lines from the file
    line = ''
    while not line or line.strip()[:2] == "//":
        line = file_handler.readline()
        if len(line) == 0:
            break
        line = line.strip()
    return line

if __name__ == "__main__":
    conn = sqlite3.connect('IndHelperDB.db')
    cursor = conn.cursor()
    #id = int(input("User ID?"))
    dirPath = input("Path?")

    #extract ID
    id = int(dirPath.split("\\")[-2].split(" ")[-1])

    job_cols = """userID, jobNum, JobTitle, CompanyName, CompanyType, areaSpec, 
                  currentPosition, [From], [To], Description, country"""

    edu_cols = """userID, eduNum, level, fieldOfStudy, SchoolName, areaSpec, 
                  currentlyEnrolled, [From], [To], country"""

    edu_cmd =  f"""INSERT INTO Edu ({edu_cols})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """

    job_cmd = f"""INSERT INTO Job ({job_cols})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """

    edu_val_list = [id]
    job_val_list = [id]

    # get the job and edu files
    files_in_subdir = os.listdir(dirPath)
    jobFiles = [dirPath + ("\\\\" if dirPath[-2:] != "\\\\" else "") + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]
    eduFiles = [dirPath + ("\\\\" if dirPath[-2:] != "\\\\" else "") + f for f in files_in_subdir if
                re.match(r'Edu\d+\.txt$', f)]


    # for each job file
    jobN = 1
    for jf in jobFiles:
        fileHandle = open(jf, 'r')
        job_val_list.append(jobN)
        jobN += 1
        for i in range(7):
            _ = nextNonBlankLine(fileHandle)
            job_val_list.append(nextNonBlankLine(fileHandle).strip() )

        _ = nextNonBlankLine(fileHandle)
        job_val_list.append(fileHandle.read().strip())
        job_val_list.append("United States")

        cursor.execute(job_cmd, tuple(job_val_list))
        job_val_list = [job_val_list[0]]

    # for each edu file
    eduN = 1
    for jf in eduFiles:
        fileHandle = open(jf, 'r')
        edu_val_list.append(eduN)
        eduN += 1
        for i in range(7):
            _ = nextNonBlankLine(fileHandle)
            edu_val_list.append(nextNonBlankLine(fileHandle).strip())

        edu_val_list.append("United States")

        cursor.execute(edu_cmd, tuple(edu_val_list))
        edu_val_list = [edu_val_list[0]]

    # Commit the changes
    conn.commit()

    # Close the connection
    conn.close()

