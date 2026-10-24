package experiment;

import java.util.ArrayList;
import java.util.List;
import java.util.Scanner;

public class bookBorrowSystem {
    private static String[] bookName = new String[50];//书名
    private static int[] bookState = new int[50];//'0'代表已经借出 '1'代表可以借
    private static String[] bookDate = new String[50];//借出日期
    private static int[] bookCount = new int[50];//借出次数
    //借阅人：
    private static String[] readerName = new String[50];
    private static String[] readerId = new String[50];
    private static String[] borrowName = new String[50];//借书名称
    private static int[] readerState = new int[50];//有无借还图书,'0'表示未还  '1'表示已还

    public static void main(String[] args) {
        initData();
        startSystem();
    }

    private static void initData() {
        bookName[0] = "数据结构";
        bookState[0] = 0;
        bookDate[0] = "2018-07-01";
        bookCount[0] = 15;
        bookName[1] = "数据库";
        bookState[1] = 1;
        bookDate[1] = "";
        bookCount[1] = 12;
        bookName[2] = "离散数学";
        bookState[2] = 1;
        bookDate[2] = "";
        bookCount[2] = 30;
        readerName[0] = "演示读者";
        readerId[0] = "DEMO-READER-001";
        borrowName[0] = "数据结构";
        readerState[0] = 0;
    }

    private static void startSystem() {
        Scanner input = new Scanner(System.in);
        int choice;
        do {
            System.out.println("-----图书借阅系统-----");
            System.out.println("0:借出排行榜  1:新增图书  2:查看图书");
            System.out.println("3:删除图书    4:借出图书  5:归还图书");
            System.out.println("6:新增借阅人  7:查看借阅人 8:删除借阅人");
            System.out.println("9:退出系统");
            System.out.printf("请输入编号：");
            choice = input.nextInt();
            input.nextLine();
            switch (choice) {
                case 0:
                    borrowRank();
                    break;
                case 1:
                    addBook(input);
                    break;
                case 2:
                    showBook();
                    break;
                case 3:
                    deleteBook(input);
                    break;
                case 4:
                    borrowBook(input);
                    break;
                case 5:
                    returnBook(input);
                    break;
                case 6:
                    addReader(input);
                    break;
                case 7:
                    showReader();
                    break;
                case 8:
                    deleteReader(input);
                    break;
                case 9:
                    System.out.println("谢谢使用！");
                    break;
                default:
                    System.out.println("输入错误，请重新输入正确的编号！");
            }
            if (choice != 9 && choice >= 0 && choice <= 8) {
                System.out.printf("输入0返回主菜单:");
                input.nextInt();
                input.nextLine();
            }
        } while (choice != 9);
        input.close();
    }

    private static void borrowRank() {
        System.out.println("-----借出排行榜-----");
        //收集图书信息的数据
        List<String> nameList = new ArrayList<>();
        List<Integer> countList = new ArrayList<>();
        for (int i = 0; i < 50; i++) {
            if (bookName[i] != null) {
                nameList.add(bookName[i]);
                countList.add(bookCount[i]);
            }
        }
        for (int i = 0; i < countList.size() - 1; i++) {
            for (int j = 0; j < countList.size() - 1 - i; j++) {
                if (countList.get(j) < countList.get(j + 1)) {
                    int temp1 = countList.get(j);
                    countList.set(j, countList.get(j + 1));
                    countList.set(j + 1, temp1);
                    String temp2 = nameList.get(j);
                    nameList.set(j, nameList.get(j + 1));
                    nameList.set(j + 1, temp2);
                }
            }
        }
        if (nameList.isEmpty()) {
            System.out.println("系统中无图书数据！");
        } else {
            for (int i = 0; i < nameList.size(); i++) {
                System.out.println((i+1) + "." + nameList.get(i) + "  借出次数：" + countList.get(i));
            }
        }
    }

    private static void addBook(Scanner input) {
        System.out.println("-----新增图书----");
        int index = -1;
        for (int i = 0; i < 50; i++) {
            if (bookName[i] == null) {
                index = i;
                break;
            }
        }
        if (index == -1) {
            System.out.println("图书存储已达上限！");
            return;
        }
        System.out.println("请输入新增图书名称：");
        String newBookName = input.nextLine().trim();
        if(newBookName.isEmpty()){
            System.out.println("图书名称不能为空！");
            return;
        }
        for (String name : bookName) {
            if (newBookName.equals(name)) {
                System.out.println("该图书已经在系统中存在！");
                return;
            }
        }
        bookName[index] = newBookName;
        bookState[index] = 1;
        bookDate[index] = "";
        bookCount[index] = 0;
        System.out.println("新增《" + newBookName + "》成功！");
    }

    private static void showBook() {
        System.out.println("-----查看图书-----");
        System.out.printf("%-20s %-10s %-15s %-10s%n", "书名", "状态", "借出日期", "借出次数");
        System.out.println("-------------------------------------------------------");
        boolean hasBook = false;
        for (int i = 0; i < 50; i++) {
            if (bookName[i] != null) {
                hasBook = true;
                String state = bookState[i] == 1 ? "可借" : "已借出";
                String date = bookState[i] == 0 ? bookDate[i] : "无";
                System.out.printf("%-20s %-10s %-15s %-10d%n", bookName[i], state, date, bookCount[i]);
            }
        }
        if (!hasBook) {
            System.out.println("系统中无图书数据！");
        }
    }

    private static void deleteBook(Scanner input) {
        System.out.println("-----删除图书-----");
        System.out.printf("请输入要删除图书的名称：");
        String deleteBookName = input.nextLine().trim();
        int deleteIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (deleteBookName.equals(bookName[i])) {
                deleteIndex = i;
                break;
            }
        }
        if (deleteIndex == -1) {
            System.out.println("未找到名称为《" + deleteBookName + "》的图书");
            return;
        }
        if (bookState[deleteIndex] == 0) {
            System.out.println("《" + deleteBookName + "》当前属于借出状态，无法删除！");
            return;
        }
        for (int i = deleteIndex; i < 49; i++) {
            bookName[i] = bookName[i + 1];
            bookState[i] = bookState[i + 1];
            bookDate[i] = bookDate[i + 1];
            bookCount[i] = bookCount[i + 1];
        }
        bookName[49] = null;
        bookState[49] = 0;
        bookDate[49] = "";
        bookCount[49] = 0;
        System.out.println("删除《" + deleteBookName + "》成功！");
    }

    private static void borrowBook(Scanner input) {
        System.out.println("-----借出图书-----");
        System.out.println("请输入要借出的图书名称：");
        String borrowBookName = input.nextLine().trim();
        System.out.println("请输入借阅人的ID号：");
        String borrowBookId = input.nextLine().trim();
        int borrowBookIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (borrowBookName.equals(bookName[i])) {
                borrowBookIndex = i;
                break;
            }
        }
        if (borrowBookIndex == -1) {
            System.out.println("没有找到名称为《" + borrowBookName + "》的书！");
            return;
        }
        if (bookState[borrowBookIndex] == 0) {
            System.out.println("《" + borrowBookName + "》当前已借出，无法借用！");
            return;
        }
        int readerIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (borrowBookId.equals(readerId[i])) {
                readerIndex = i;
                break;
            }
        }
        if (readerIndex == -1) {
            System.out.println("未找到ID为" + borrowBookId + "的借阅人，请先注册！");
            return;
        }
        if (readerState[readerIndex] == 0) {
            System.out.println("该借阅人有未归还的图书，无法借阅！");
            return;
        }
        System.out.printf("请输入借出日期：");
        String borrowDate = input.nextLine().trim();
        bookState[borrowBookIndex] = 0;
        bookDate[borrowBookIndex] = borrowDate;
        bookCount[borrowBookIndex]++;
        borrowName[readerIndex] = borrowBookName;
        readerState[readerIndex] = 0;
        System.out.println("《" + borrowBookName + "》借出成功！借阅人：" + readerName[readerIndex]);
    }

    private static void returnBook(Scanner input) {
        System.out.println("-----归还图书-----");
        System.out.printf("请输入要归还的图书的名称：");
        String returnBookName = input.nextLine().trim();
        int returnBookIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (returnBookName.equals(bookName[i]) && bookState[i] == 0) {
                returnBookIndex = i;
                break;
            }
        }
        if (returnBookIndex == -1) {
            System.out.println("未找到名称为《" + returnBookName + "》的书！");
            return;
        }
        int readerIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (returnBookName.equals(borrowName[i]) && readerState[i] == 0) {
                readerIndex = i;
                break;
            }
        }
        if (readerIndex == -1) {
            System.out.printf("未找到名称为《" + returnBookName + "》的书！");
            return;
        }
        System.out.println("请输入归还日期：");
        String returnDate = input.nextLine().trim();
        try {
            int lendDay = Integer.parseInt(bookDate[returnBookIndex].split("-")[2]);
            int returnDay = Integer.parseInt(returnDate.split("-")[2]);
            int borrowDay = returnDay - lendDay;
            if (borrowDay < 0) {
                borrowDay += 30;
            }
            double rent = borrowDay * 0.5;
            bookState[returnBookIndex] = 1;
            bookDate[returnBookIndex] = "";
            borrowName[readerIndex] = "无";
            readerState[readerIndex] = 1;
            System.out.println("《" + returnBookName + "》归还成功");
            System.out.println("借阅人：" + readerName[readerIndex]);
            System.out.println("借阅时长：" + borrowDay + "天，应付租金：" + rent + "元");
        }catch(Exception e) {
            System.out.println("日期格式错误！请使用YYYY-MM-DD格式！");
        }
    }

    private static void addReader(Scanner input) {
        System.out.println("-----新增借阅人-----");
        int readerIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (readerName[i] == null) {
                readerIndex = i;
                break;
            }
        }
        if (readerIndex == -1) {
            System.out.println("借阅人已达上限！");
            return;
        }
        System.out.printf("请输入借阅人信息：");
        String newReaderName = input.nextLine().trim();
        System.out.printf("请输入借阅人ID：");
        String newReaderId = input.nextLine().trim();
        for (String id : readerId) {
            if (newReaderId.equals(id)) {
                System.out.println("该Id已被注册！");
                return;
            }
        }
        readerName[readerIndex] = newReaderName;
        readerId[readerIndex] = newReaderId;
        borrowName[readerIndex] = "无";
        readerState[readerIndex] = 1;
        System.out.println("新增借阅人【" + newReaderName + "】成功！");
    }

    private static void showReader() {
        System.out.println("-----查看借阅人-----");
        System.out.printf("%-10s %-20s %-20s%n", "姓名", "ID号", "当前借阅图书");
        System.out.println("-------------------------------------------");
        boolean hasReader = false;
        for (int i = 0; i < 50; i++) {
            if (readerName[i] != null) {
                hasReader = true;
                System.out.printf("%-10s %-20s %-20s%n", readerName[i], readerId[i], borrowName[i]);
            }
        }
        if (!hasReader) {
            System.out.println("系统中暂无借阅人！");
        }
    }

    private static void deleteReader(Scanner input) {
        System.out.println("-----删除借阅人-----");
        System.out.println("请输入要删除的借阅人ID号：");
        String deleteReaderId = input.nextLine().trim();
        int deleteReaderIndex = -1;
        for (int i = 0; i < 50; i++) {
            if (deleteReaderId.equals(readerId[i])) {
                deleteReaderIndex = i;
                break;
            }
        }
        if (deleteReaderIndex == -1) {
            System.out.println("未找到ID号为" + deleteReaderId + "的借阅人");
            return;
        }
        if (readerState[deleteReaderIndex] == 0) {
            System.out.println("该借阅人有未还图书，不能删除！");
            return;
        }
        String deleteReaderName = readerName[deleteReaderIndex];
        for (int i = deleteReaderIndex; i < 49; i++) {
            readerName[i] = readerName[i + 1];
            readerId[i] = readerId[i + 1];
            borrowName[i] = borrowName[i + 1];
            readerState[i] = readerState[i + 1];
        }
        readerName[49] = null;
        readerId[49] = null;
        borrowName[49] = "无";
        readerState[49] = 1;
        System.out.println("删除借阅人【" + deleteReaderName + "】成功！");
    }
}
