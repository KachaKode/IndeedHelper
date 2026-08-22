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


function findAndClick(aspect_, searchType_, chooser_, indexInList_ = 0, txtCond = '', findFrom = null) {
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
        if (aspect_ === 'text') {
            elements = Array.from(searchContext.querySelectorAll('*')).filter(el => {
                if (searchType_ === 'contains') {
                    return el.textContent.includes(chooser_);
                } else if (searchType_ === 'match') {
                    return el.textContent === chooser_;
                }
            });
        } else if (aspect_ === 'id') {
            elements = Array.from(searchContext.querySelectorAll('*')).filter(el => {
                if (searchType_ === 'contains') {
                    return el.id.includes(chooser_);
                } else if (searchType_ === 'match') {
                    return el.id === chooser_;
                }
            });
        } else if (aspect_ === 'class') {
            elements = Array.from(searchContext.querySelectorAll('*')).filter(el => {
                if (searchType_ === 'contains') {
                    return el.className.includes(chooser_);
                } else if (searchType_ === 'match') {
                    return el.className.split(' ').includes(chooser_);
                }
            });
        } else if (aspect_ === 'element') {
            elements = Array.from(searchContext.querySelectorAll(chooser_));
        } else {
            // Treat aspect_ as an attribute name
            elements = Array.from(searchContext.querySelectorAll('*')).filter(el => {
                const attrValue = el.getAttribute(aspect_);
                if (attrValue !== null) {
                    if (searchType_ === 'contains') {
                        return attrValue.includes(chooser_);
                    } else if (searchType_ === 'match') {
                        return attrValue === chooser_;
                    }
                }
                return false;
            });
        }
    }

    if (elements.length === 0) {
        console.log('No matching elements found');
        return null;
    }

    if (indexInList_ === 'all') {
        return elements;
    } else {
        const index = parseInt(indexInList_);
        if (index >= 0 && index < elements.length) {
            const element = elements[index];
            if (txtCond === '' || element.textContent === txtCond) {
                //element.click();
				smartClick(element, false);
            }
            return element;
        } else {
            console.log('Invalid index');
            return null;
        }
    }
}
