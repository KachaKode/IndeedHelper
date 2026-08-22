function findClosestRelatives(refWhat, refType, refXpath, targetWhat, targetType, targetXpath, refElementFilterType = "*", limit = 10, srchLvlLmt = Infinity) {
    // Find the reference element
    let reference = findAndClick(refWhat, refType, refXpath, 0, "^&*(", null, refElementFilterType);

    if (reference === null) {
        console.log("Reference element not found.");
        return;
    }

    let relz = [];
    let level = 0;

    // Initialize relz array in JS context

    while (true) {
        // Find target elements based on the reference element
        let elements = findAndClick(targetWhat, targetType, targetXpath, 'all', "^&*(", reference, "*");

        // If elements are found, add them to relatives
        if (elements.length > 0) {
            relz = elements;
            break;
        }

        // Move up to the parent node
        reference = reference.parentNode;

        // Check if already at the top level
        if (reference === null || level >= srchLvlLmt) {
            break;
        }

        level++;
    }

    return relz
}

function smartClick(elementToClick, newTab) {
	if (!elementToClick || !(elementToClick instanceof HTMLElement)) {
		console.error("Invalid element provided.");
		return;
	}

	if (newTab) {
		const event = new MouseEvent('click', {
			bubbles: true,
			cancelable: true,
			view: window,
			ctrlKey: true
		});
		elementToClick.dispatchEvent(event);
	} else {
		elementToClick.click();
	}
}

function clickAll(elementsToClick){
	elementsToClick.forEach( (ele) => {
		smartClick(ele); 
	});
}

function reduceChoice(ele, aspect){
	if (aspect === "text") return ele.textContent;
	else if (aspect === "id") return ele.id ;
	else if (aspect === "class") return ele.className ;
	else return ele.getAttribute(aspect);
}

let errList = [];

function findAndClick(aspect_, searchType_, chooser_, indexInList_ = 0, txtCond = '', findFrom = null, eleFilter = '*') {
    let elements = [];
    const searchContext = findFrom || document;
    const choosers = Array.isArray(chooser_) ? chooser_ : [chooser_];

    const processElement = (element) => {
        if (txtCond === '' || element.textContent === txtCond) {
            // element.click();
            smartClick(element, false);
        }
        return element;
    };

    const findElements = (chooser) => {
        if (searchType_ === 'whole' || aspect_ === 'whole') {
            // If searchType_ is 'whole', use XPath to find elements
			if (findFrom && chooser[0]!="."){
				chooser = "." + chooser ;
			}
            let xpathResult = document.evaluate(chooser, searchContext, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let i = 0; i < xpathResult.snapshotLength; i++) {
                elements.push(xpathResult.snapshotItem(i));
            }
        } else {
            // Find elements based on aspect_
            if (aspect_ === 'element') {
                elements.push(...Array.from(searchContext.querySelectorAll(chooser)));
            } else {
                elements.push(...Array.from(searchContext.querySelectorAll(eleFilter)).filter(el => {
                    try {
                        if (searchType_ === 'contains') {
                            return reduceChoice(el, aspect_).includes(chooser);
                        } else if (searchType_ === 'match') {
							
                            return reduceChoice(el, aspect_) === chooser;
                        }
                    } catch (e) {
                        console.log("error is:");
                        console.log(e);
                        errList.push(el);
                        return false;
                    }
                }));
            }
        }
    };

    choosers.forEach(chooser => findElements(chooser));

    if (elements.length === 0) {
        console.log('No matching elements found');
        return indexInList_ === 'all' ? elements : null;
    }

    if (indexInList_ === 'all') {
        return elements;
    } else {
        const index = parseInt(indexInList_);
        if (index >= 0 && index < elements.length) {
            return processElement(elements[index]);
        } else {
            console.log('Invalid index');
            return null;
        }
    }
}

function fillDropDown(dropElement, choiceText){
	var correctOption = null;

	while (!correctOption && choiceText.length > 0){
		correctOption = Array.from(dropElement.children).find( (child_opt) => {
			return child_opt.textContent == choiceText ;
		}  );
		
		choiceText = choiceText.slice(1, -1).trim();

	}
	
	if (correctOption){
		dropElement.value = correctOption.value;
		return true ;
	}
	else {
		return null;
	}
}


function findAndClick1(aspect_, searchType_, chooser_, indexInList_ = 0, txtCond = '', findFrom = null, eleFilter='*') {
    let elements = [];
    const searchContext = findFrom || document;

    if (searchType_ === 'whole') {
        // If searchType_ is 'whole', use XPath to find elements
        let xpathResult = document.evaluate(chooser_, searchContext, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        for (let i = 0; i < xpathResult.snapshotLength; i++) {
            elements.push(xpathResult.snapshotItem(i));
        }
    } else {
        // Find elements based on aspect_
		 if (aspect_ === 'element') {
            elements = Array.from(searchContext.querySelectorAll(chooser_));
        }
		else {
			elements = Array.from(searchContext.querySelectorAll(eleFilter)).filter(el => {
				try {
					if (searchType_ === 'contains') {
						return reduceChoice(el, aspect_).includes(chooser_);
					} else if (searchType_ === 'match') {
						return reduceChoice(el, aspect_) === chooser_;
					}
				}
				catch (e){
					console.log("error is:");
					console.log(e);
					errList.push(el);
					return false;
				}
            });
		}
    }

    if (elements.length === 0) {
        console.log('No matching elements found');
        return indexInList_ === 'all' ? elements : null;
    }

    if (indexInList_ === 'all') {
        return elements;
    } else {
        const index = parseInt(indexInList_);
        if (index >= 0 && index < elements.length) {
            const element = elements[index];
            if (txtCond === '' || element.textContent === txtCond) {
                // element.click();
				smartClick(element, false);
            }
            return element;
        } else {
            console.log('Invalid index');
            return null;
        }
    }
}
